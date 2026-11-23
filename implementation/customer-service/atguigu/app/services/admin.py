import httpx
from atguigu.common.settings import get_settings
from atguigu.app.services.auth import encode_access_token
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from atguigu.app.models.enums import HandoffStatus, ConversationMode, MessageRole
from atguigu.app.models.models import Conversations, Handoff, Message
from atguigu.app.services.realtime import RealtimeService
from atguigu.common.utils import get_uid, get_utcnow


class AdminService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._realtime_service = RealtimeService(session)

    async def get_handoffs(self) -> list[Handoff]:
        stmt = select(Handoff).where(Handoff.status.in_([HandoffStatus.WAITING, HandoffStatus.ACTIVE])).order_by(
            Handoff.created_at)
        handoff = list((await self._session.scalars(stmt)).all())
        return handoff

    async def get_handoff_message(self, handoff_id, staff_id) -> dict[str, Any]:
        h=await self._session.get(Handoff,handoff_id)
        if not h:
            raise HTTPException(404,"NOT_FOUND")
        if h.staff_id and h.staff_id!=staff_id:
            raise HTTPException(403,"其他客服已接入")
        ctx=dict(h.context_snapshot or {})
        ctx.update(tickets=[],ticket_lookup="设备未确认")
        d=ctx.get("device")
        if d:
            try:
                async with httpx.AsyncClient(timeout=4,trust_env=False) as client:
                    resp=await client.get(get_settings().ecommerce_base_url+"/api/v1/repair-tickets",
                        params={"device_id":d["device_id"]},headers={"Authorization":"Bearer "+encode_access_token(h.user_id)})
                    resp.raise_for_status()
                    ctx["tickets"]=resp.json()["data"]
                    ctx["ticket_lookup"]="已查到" if ctx["tickets"] else "无记录"
            except httpx.HTTPError:
                ctx["ticket_lookup"]="待重查"
        stmt = select(Message).join(Handoff, Message.conversation_id == Handoff.conversation_id).where(
            Handoff.id == handoff_id).order_by(Message.id)
        conversation_message = (await self._session.scalars(stmt)).all()
        return {"messages": conversation_message,"handoff_context":ctx,"summary":h.summary}

    async def accept_handoff(self, handoff_id, staff_id):
        # 客服接单 这里要注意两个逻辑 先判断状态 在接单以免抢单 且handoff表要加锁
        handoff, conversation = await self._get_handoff_conversation(handoff_id)
        if handoff.status != HandoffStatus.WAITING or conversation.mode!=ConversationMode.QUEUED:
            raise HTTPException(status_code=409, detail="该工单已被接入，请勿重试抢单")
        handoff.status = HandoffStatus.ACTIVE
        handoff.staff_id = staff_id

        # 修改会话模式 从Queued切换成human
        conversation.context_version+=1
        conversation.mode = ConversationMode.HUMAN

        # 保存提示开场白到message和realtime表
        self._save_human_reply(conversation, reply_text=f"客服{staff_id}已接入单，请问您有什么需要帮助的？")

        await self._session.commit()

    async def reply_messages(self, handoff_id, payload, staff_id):
        handoff, conversation = await self._get_handoff_conversation(handoff_id)
        self._require_assigned(handoff,staff_id)
        self._save_human_reply(conversation, payload.text)
        await self._session.commit()

    async def resolve_handoff(self, handoff_id, staff_id):
        handoff, conversation = await self._get_handoff_conversation(handoff_id)
        # 客服结束工单 会话状态变成AI  工单状态变成resolve
        self._require_assigned(handoff,staff_id)
        conversation.context_version+=1
        conversation.mode = ConversationMode.AI
        handoff.status = HandoffStatus.RESOLVED
        self._save_human_reply(conversation, reply_text=f"人工客服已结束，之后由AI客服继续为您服务")
        await self._session.commit()

    @staticmethod
    def _require_assigned(handoff,staff_id):
        if handoff.staff_id!=staff_id or handoff.status!=HandoffStatus.ACTIVE:
            raise HTTPException(403,"需要当前接单客服")

    async def get_metrics(self):
        return {
            "conversations": await self._get_count(Conversations.id),
            "handoffs": await self._get_count(Handoff.id),
            "queued": await self._get_count(Conversations.id, Conversations.mode == ConversationMode.QUEUED),
            "human": await self._get_count(Conversations.id, Conversations.mode == ConversationMode.HUMAN)
        }

    async def _get_count(self, col, *condition_expr):
        return await self._session.scalar(select(func.count(col)).where(*condition_expr))

    async def _get_handoff_conversation(self, handoff_id) -> tuple[Handoff, Conversations]:
        cid=await self._session.scalar(select(Handoff.conversation_id).where(Handoff.id==handoff_id))
        if not cid:
            raise HTTPException(404,"NOT_FOUND")
        conversation=await self._session.scalar(select(Conversations).where(Conversations.id==cid).with_for_update())
        handoff=await self._session.scalar(select(Handoff).where(Handoff.id==handoff_id).with_for_update())
        return handoff, conversation

    def _save_human_reply(self, conversation, reply_text):
        # 构造message消息
        message = Message(
            message_id=get_uid("msg"),
            conversation_id=conversation.id,
            role=MessageRole.HUMAN,
            message_type="text",
            content={"text": reply_text}
        )
        self._session.add(message)

        # 修改conversation最后活跃时间
        conversation.last_activity_at = get_utcnow()

        # 调用add_event报错realtime消息
        self._realtime_service.add_event(message, conversation, notify_user=True, notify_staff=False)
