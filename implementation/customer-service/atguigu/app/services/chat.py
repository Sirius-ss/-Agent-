from copy import deepcopy
from hashlib import sha256
import httpx
from atguigu.app.services.auth import encode_access_token
from fastapi import HTTPException
from atguigu.app.services.scenes import smoke, handoff
from datetime import timedelta
from typing import Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from atguigu.app.models.enums import ConversationMode, MessageRole, TurnStatus
from atguigu.app.models.models import Message, Conversations, ConversationTurn
from atguigu.app.schemas import ChatMessageRequest
from atguigu.app.services.realtime import RealtimeService
from atguigu.common.settings import get_settings
from atguigu.common.utils import get_utcnow, get_uid


class ChatService:
    def __init__(self, session: AsyncSession):
        self._realtime_services = RealtimeService(session)
        self._session = session
        self._get_setting = get_settings()

    async def get_chat_history(self, user_id: str, conversation_id=None, *, all_scenes=False) -> dict[str:Any]:
        # 已经拿到用户id了 用用户id去message表中查询该用户的所有信息  最外层要用当前会话的会话id和会话模式包裹
        # 关联message表和conversation表拿到该用户的所有信息
        conversation = await self._resolve_conversation(user_id,conversation_id,history=True)
        stmt=select(Message, Conversations.service_scene).join(Conversations).where(Conversations.user_id==user_id)
        if conversation_id:
            stmt=stmt.where(Conversations.id==conversation_id)
        elif not all_scenes:
            stmt=stmt.where(Conversations.service_scene=="ECOMMERCE")
        records=(await self._session.execute(stmt.order_by(Message.id))).all()
        conversation_messages=[dict(conversation_id=m.conversation_id,message_id=m.message_id,
                                    service_scene=scene,role=m.role,type=m.message_type,content=m.content) for m,scene in records]
        # 提交
        await self._session.commit()
        # 返回
        return {
            "conversation_id": conversation.id,
            "service_scene": conversation.service_scene,
            "conversation_mode": conversation.mode,
            "service_context": conversation.service_context,
            "context_version":conversation.context_version,
            "messages": conversation_messages
        }

    async def enter_appliance(self, user_id: str, source_id: str):
        target_id = "entry_" + sha256((user_id + ":" + source_id).encode()).hexdigest()
        await self._session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": target_id})
        source = await self._session.scalar(select(Message).join(Conversations).where(
            Conversations.user_id == user_id, Conversations.service_scene == "ECOMMERCE",
            Message.role == MessageRole.USER, Message.message_type == "text", Message.message_id == source_id))
        if source is None:
            raise HTTPException(404, "NOT_FOUND")
        existing = await self._session.scalar(select(Message).where(Message.message_id == target_id))
        if existing:
            return {"conversation_id": existing.conversation_id, "message_id": target_id}
        offer = await self._session.scalar(select(Message.id).where(
            Message.conversation_id == source.conversation_id, Message.role == MessageRole.AI,
            Message.content["page_action"]["action_code"].as_string() == "ENTER_APPLIANCE",
            Message.content["page_action"]["source_id"].as_string() == source_id))
        if offer is None:
            raise HTTPException(409, "未找到对应的家电售后引导")
        target = await self._create_or_get_conversation(user_id, "APPLIANCE_SERVICE", target_id)
        await self._session.flush()
        self._session.add(Message(conversation_id=target.id, message_id=target_id, role=MessageRole.USER,
                                  message_type="text", content={"text": source.content["text"]}))
        report = source.content["text"]
        if smoke(report):
            await handoff(self, target, "正在冒烟", report, True)
        else:
            await self._create_or_get_turn(target.id)
        await self._session.commit()
        return {"conversation_id": target.id, "message_id": target_id}

    async def process_chat_message(self,
                                   user_id: str,
                                   payload: ChatMessageRequest
                                   ):
        # 现在从路由传过来了用户id和payload(message_id,type,content)
        if payload.message_id.startswith("entry_"):
            raise HTTPException(422, "保留的消息标识")
        conversation=await self._resolve_conversation(user_id,payload.conversation_id)
        # 1.message_id去重
        stmt = select(Message).where(Message.message_id == payload.message_id)
        message = await self._session.scalar(stmt)
        if message:
            if (message.conversation_id != conversation.id or message.content != payload.content
                    or message.message_type != payload.type):
                raise HTTPException(409, "消息标识冲突")
            return
        # 获取有效会话id 若无有效则创建新的

        # 创建新消息对象 并 将信息保存到messages表中 修改会话的激活时间
        message = Message(
            message_id=payload.message_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            message_type=payload.type,
            content=payload.content
        )
        self._session.add(message)
        conversation.last_activity_at = get_utcnow()

        if payload.type == "step_feedback":
            if await self._apply_step_feedback(conversation, user_id, payload.content):
                await self._session.commit()
                return
        if conversation.service_scene=="APPLIANCE_SERVICE":
            content=str(payload.content.get("text",""))
            if smoke(content) or payload.type=="request_handoff" or content.strip()=="转人工":
                await handoff(self,conversation,"正在冒烟" if smoke(content) else "用户请求人工",content,smoke(content))
                await self._session.commit()
                return
        # 消息根据会话模式分流 if 若会话模式是AI则 获取turn 否则往realtime_event中存消息
        if conversation.mode == ConversationMode.AI:
            await self._create_or_get_turn(conversation.id)
        else:
            self._realtime_services.add_event(message, conversation, notify_staff=True)
        # 统一提交 同生共死
        await self._session.commit()

    async def _apply_step_feedback(self, conversation, user_id, body):
        state = deepcopy(conversation.service_context or {})
        pending = state.get("pending_step") or {}
        device = state.get("device") or {}
        outcome = body.get("outcome")
        if (conversation.service_scene != "APPLIANCE_SERVICE" or conversation.mode != ConversationMode.AI
                or type(body.get("context_version")) is not int or body["context_version"] != conversation.context_version
                or not pending or body.get("step_id") != pending["id"] or not device
                or body.get("device_id") != device["device_id"] or outcome not in ("resolved", "unresolved")):
            raise HTTPException(409, "诊断卡已更新，请刷新后使用最新步骤。")
        url = self._get_setting.ecommerce_base_url.removesuffix("/api/v1").rstrip("/") + "/api/v1/devices"
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                result = await client.get(url, headers={"Authorization": "Bearer " + encode_access_token(user_id)})
                result.raise_for_status()
            if not any(d["device_id"] == device["device_id"] and d["model_code"] == device["model_code"]
                       for d in result.json()["data"]):
                raise HTTPException(404, "NOT_FOUND")
        except httpx.HTTPError as exc:
            raise HTTPException(503, "设备归属暂时无法核验") from exc
        plan = state.get("diagnostic_plan")
        if not plan:
            from urllib.parse import quote
            chunk = quote(state.get("chunk_id") or "", safe="")
            url = self._get_setting.ai_service_url.rstrip("/") + "/internal/v1/diagnostic-plans/" + chunk
            try:
                async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                    result = await client.get(url, params={"device_id": device["device_id"]}, headers={
                        "Authorization": "Bearer " + encode_access_token(user_id),
                        "X-Internal-Service-Token": self._get_setting.internal_service_token})
                    if result.status_code == 404:
                        raise HTTPException(409, "原说明书已更新，请重新发送故障码。")
                    result.raise_for_status()
                plan = state["diagnostic_plan"] = result.json()
            except httpx.HTTPError as exc:
                raise HTTPException(503, "原说明书暂时无法读取，请稍后重试。") from exc
        index = len(state.get("steps", []))
        citation = plan["citation"]
        if (citation["model_code"] != device["model_code"] or citation["id"] != state.get("chunk_id")
                or index >= len(plan["steps"]) or pending != {
                    "id": f"{citation['id']}:{index}", "text": plan["steps"][index]}):
            raise HTTPException(409, "步骤依据已更新，请重新诊断。")
        state.setdefault("steps", []).append({**pending, "outcome": outcome})
        state["pending_step"] = None
        reply = {"reply_type": "ANSWER", "citations": [citation]}
        if outcome == "resolved":
            state = {"workflow_stage": "resolved"}
            reply["text"] = "设备已恢复，本次自查结束。下次咨询故障时，请重新确认对应设备。"
        elif index + 1 == len(plan["steps"]):
            state["workflow_stage"] = "repair_available"
            reply.update(text="适用自查步骤已完成，可打开维修预览或转人工。",
                         page_action={"action_code": "OPEN_REPAIR_PREVIEW", "device_id": device["device_id"]})
        else:
            step = {"id": f"{citation['id']}:{index+1}", "text": plan["steps"][index+1]}
            state["pending_step"] = step
            reply.update(text="请核对下一项自查步骤。", step=step)
        conversation.service_context = state
        conversation.context_version += 1
        self._save_ai_reply(reply, conversation)
        return True

    async def _resolve_conversation(self,user_id,cid,history=False):
        if not cid:
            return await self._create_or_get_conversation(user_id)
        conv=await self._session.scalar(select(Conversations).where(Conversations.user_id==user_id,Conversations.id==cid).with_for_update())
        if not conv:
            raise HTTPException(404,"NOT_FOUND")
        if not history:
            if not conv.thread_key.startswith("RT_") and conv.mode==ConversationMode.AI and get_utcnow()-conv.last_activity_at>=timedelta(minutes=self._get_setting.conversation_idle_timeout_minutes):
                conv.mode=ConversationMode.CLOSED
                conv.context_version+=1
                await self._session.commit()
            if conv.mode==ConversationMode.CLOSED:
                raise HTTPException(409,"CONVERSATION_CLOSED")
        return conv

    async def _create_or_get_conversation(self, user_id: str, scene="ECOMMERCE", thread_key="", initial_context=None):
        await self._session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),{"key":user_id+scene+thread_key})
        # 查询该用户下是否是活跃会话 无活跃会话则创建 有活跃会话还需判断当mode是AI时 有没有过期 若过期则将mode设置为close且创建新的
        stmt = select(Conversations).where(Conversations.user_id == user_id,
                                           Conversations.mode != ConversationMode.CLOSED, Conversations.service_scene==scene, Conversations.thread_key==thread_key).with_for_update()
        conversation = await self._session.scalar(stmt)
        if conversation:
            # 如果存在活跃的会话 且会话模式是AI 判断是否过期，QUEUED和HUMAN没有过期时间说法
            timeout = timedelta(minutes=self._get_setting.conversation_idle_timeout_minutes)
            if not thread_key.startswith("RT_") and conversation.mode == ConversationMode.AI and get_utcnow() - conversation.last_activity_at >= timeout:
                # 修改过期的会话状态为过期
                conversation.mode = ConversationMode.CLOSED
                conversation.context_version+=1
                await self._session.flush()
            else:
                return conversation
        # 创建新的会话
        conversation = Conversations(
            id=get_uid("conv"),
            user_id=user_id,service_scene=scene,thread_key=thread_key,service_context=initial_context or {},context_version=0,
            mode=ConversationMode.AI
        )
        # 保存会话
        self._session.add(conversation)
        # 返回
        return conversation

    async def _create_or_get_turn(self, conversation_id):
        # 查询消息轮次表中 是否有处于COLLECTION的轮次 若无则创建 有则复用 返回
        stmt = select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id,
                                              ConversationTurn.status == TurnStatus.COLLECTION)
        turn = await self._session.scalar(stmt)
        if turn is None:
            turn = ConversationTurn(
                conversation_id=conversation_id,
                status=TurnStatus.COLLECTION,
                collect_until=get_utcnow() + timedelta(milliseconds=self._get_setting.message_merge_delay_ms)
            )
        self._session.add(turn)
        return turn

    async def claim_turn_and_build_payload(self):
        # 获取一个活跃中的turn
        stmt = (select(ConversationTurn).where(ConversationTurn.status == TurnStatus.COLLECTION,
                                               ConversationTurn.collect_until <= get_utcnow())
                .where(~ConversationTurn.conversation_id.in_(select(ConversationTurn.conversation_id).where(ConversationTurn.status==TurnStatus.RUNNING)))
                .order_by(ConversationTurn.collect_until).limit(1).with_for_update(skip_locked=True))
        claimed_turn = await self._session.scalar(stmt)
        # print(get_utcnow())
        # 没有turn则返回空
        if not claimed_turn:
            return None

        # 拿到一个会话 并加锁
        stmt = select(Conversations).where(Conversations.id == claimed_turn.conversation_id).with_for_update()
        conversation = await self._session.scalar(stmt)

        # 修改turn表中的状态和尝试次数
        claimed_turn.status = TurnStatus.RUNNING
        claimed_turn.attempts += 1

        # 获取该会话中最新一条message_id 下限
        latest_user_message_id = await self._get_latest_message_id(str(conversation.id))
        # 修改turn表的snapshot_message_id
        claimed_turn.snapshot_message_id = latest_user_message_id

        # 构建请求载荷
        if conversation.mode!=ConversationMode.AI:
            claimed_turn.status=TurnStatus.SUPERSEDE
            await self._session.commit()
            return None
        payload: dict[str, Any] = await self._build_request_payload(claimed_turn, conversation)

        payload.update(service_scene=conversation.service_scene,service_context=conversation.service_context,context_version=conversation.context_version)
        # 提交
        await self._session.commit()

        # 返回
        return claimed_turn, payload, str(conversation.user_id)

    async def finish_turn(self, claim_turn: ConversationTurn, ai_result, error, payload):

        # 查询当前轮次对应的会话
        stmt = (select(Conversations).where(Conversations.id == claim_turn.conversation_id)
                .execution_options(populate_existing=True).with_for_update())
        conversation = await self._session.scalar(stmt)

        if (conversation.mode!=ConversationMode.AI or conversation.context_version!=payload["context_version"]
                or conversation.service_scene!=payload["service_scene"]
                or claim_turn.snapshot_message_id!=await self._get_latest_message_id(conversation.id)):
            claim_turn.status=TurnStatus.SUPERSEDE
            await self._session.commit()
            return
        # 判断调AI接口是否成功
        if error:
            # 失败还有重试次数
            if claim_turn.attempts <= self._get_setting.ai_worker_max_attempts:
                claim_turn.status = TurnStatus.COLLECTION  # TODO 了状态还要改 until时间
                claim_turn.collect_until = get_utcnow() + timedelta(
                    seconds=self._get_setting.ai_worker_retry_delay_seconds)
            else:
                # 无重试次数
                claim_turn.status = TurnStatus.FAILED
                # 往message realtime插入ai调用失败信息

                conversation.context_version+=1
                conversation.service_context={**conversation.service_context,"user_report":str(payload["messages"][-1]["content"].get("text",""))}
                conversation.mode = ConversationMode.QUEUED
                self._realtime_services.add_handoff(conversation,
                                                    summary="AI 服务多次调用异常，系统自动降级转接人工客服")
                self._save_ai_reply({"text": "当前智能助手正忙，已自动为您转接人工客服处理，请稍候。"}, conversation)

            await self._session.commit()
            return
        # 判断是否插话
        if claim_turn.snapshot_message_id != await self._get_latest_message_id(claim_turn.conversation_id):
            # 插话
            claim_turn.status = TurnStatus.SUPERSEDE
            await self._session.commit()
            return
        # 判断是否转人工
        claim_turn.status = TurnStatus.COMPLETED

        # 转人工
        if ai_result['reply_type'] == "REQUEST_HANDOFF":
            self._realtime_services.add_handoff(conversation, ai_result["summary"])
            conversation.mode = ConversationMode.QUEUED  # TODO没有改会话模式为QUEUED

        action = ai_result.get("page_action") or {}
        if action.get("action_code") == "ENTER_APPLIANCE":
            source = await self._session.get(Message, claim_turn.snapshot_message_id)
            if conversation.service_scene == "ECOMMERCE" and source and source.message_type == "text":
                action["source_id"] = source.message_id
            else:
                ai_result["page_action"] = None
        state=ai_result.pop("service_context",None)
        if state is not None and state!=conversation.service_context:
            conversation.service_context=state
            conversation.context_version+=1
        self._save_ai_reply(ai_result, conversation)
        await self._session.commit()

    def _save_ai_reply(self, ai_result: dict[str:Any], conversation: Conversations):
        # 还要设置一个键来判断要插入realtime表的哪个target
        # 插入message表
        message = Message(
            message_id=get_uid("msg"),
            conversation_id=conversation.id,
            role=MessageRole.AI,
            message_type="text",
            content=ai_result
        )
        self._session.add(message)

        # 修改会话最后一个活跃时间
        conversation.last_activity_at = get_utcnow()  # TODO 别忘记

        # 插入realtime表
        self._realtime_services.add_event(message, conversation,
                                          notify_user=True,
                                          notify_staff=conversation.mode == ConversationMode.QUEUED)

    async def _get_latest_message_id(self, conversation_id):
        stmt = select(func.max(Message.id)).where(Message.conversation_id == conversation_id,
                                                  Message.role == MessageRole.USER)
        return await self._session.scalar(stmt)

    async def _build_request_payload(self, claimed_turn, conversation):
        # 需要拿去的轮次消息上限 拿该轮会话中非user角色的最后一条消息
        stmt = select(func.max(Message.id)).where(Message.conversation_id == conversation.id,
                                                  Message.role != MessageRole.USER)
        lasted_reply_message_id = await self._session.scalar(stmt) or 0  # 做一个兜底
        # 查询范围
        current_turn_messages_stmt = select(Message).where(Message.id > lasted_reply_message_id,
                                                           Message.id <= claimed_turn.snapshot_message_id,
                                                           Message.conversation_id == conversation.id).order_by(
            Message.id)
        current_turn_messages = (await self._session.scalars(current_turn_messages_stmt)).all()

        # 要返回payload message history conversation_id 现在需要构造history
        stmt = select(Message).where(Message.conversation_id == conversation.id,
                                     Message.id < current_turn_messages[0].id).order_by(Message.id.desc()).limit(30)
        histories = reversed((await self._session.scalars(stmt)).all())
        return {
            "conversation_id": conversation.id,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "type": message.message_type
                }
                for message in current_turn_messages
            ],
            "history": [
                {
                    "role": history.role,
                    "content": history.content,
                    "type": history.message_type
                }
                for history in histories
            ]
        }
