from typesafe_sdk._core.errors import TypeSafeInternalServerError
import logging
import re
import time
from typing import Any

from fastapi import HTTPException, status
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from atguigu.agent.harness.run.context import build_messages, AgentRunContext, mentioned_appliance_models
from atguigu.agent.harness.validator.jev import check_input
from atguigu.agent.harness.validator.validator import ValidateAgentOutError, Validator, build_request
from atguigu.app.models.enums import AgentTraceStatus, ReplyType
from atguigu.app.models.models import AgentTrace
from atguigu.app.schemas import AgentRunRequest, CurrentUser
from atguigu.common.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _needs_fault_description(query: str, latest: dict[str, Any]) -> bool:
    """识别先确认了设备身份、但尚未描述故障的场景。"""
    if latest.get("type") != "device_choice":
        return False
    from atguigu.app.services.manuals import fault_code
    if not query.strip():
        return True
    if fault_code(query):
        return False
    if re.fullmatch(
        r"(?:我的|我家(?:的)?)?(?:DEMO[\s-]*)?(?:空调|洗衣机|设备|家电|A-DEMO|W-DEMO)?"
        r"[\s，。！？]*(?:(?:出现了?|发生了?|有了?|出了?)?(?:故障|问题|异常)|坏了)?[\s，。！？!?.]*",
        query.strip(), re.IGNORECASE,
    ):
        return True

    # 用户已说出症状时，即使同时询问序列号或不确定设备，也继续按症状检索。
    symptom_hints = (
        "漏水", "滴水", "不制冷", "不制热", "不启动", "无法启动", "不工作", "异响", "噪音",
        "震动", "冒烟", "漏电", "异味", "不排水", "排水慢", "不脱水", "不进水", "闪烁",
        "结冰", "开不了", "关不了", "故障", "异常", "有问题", "坏了", "不转", "停机", "发烫",
    )
    if any(hint in query for hint in symptom_hints):
        return False
    from atguigu.agent.harness.validator.appliance import asks_for_device_identification_help
    return bool(asks_for_device_identification_help(query))


class AgentExecutor:
    def __init__(self, session: AsyncSession, *, agent: Any):
        self._setting = get_settings()
        self._session = session
        self._agent = agent
        self._validator = Validator(session)  # 用来校验

    async def start_run(self,
                        payload: AgentRunRequest,
                        current_user: CurrentUser
                        ) -> dict[str, Any]:
        """
        customer_service的ai-worker请求ai-service，在请求路由处已经完成JWT和服务令牌的双重校验，在这个任务中需获得session 、agent 要完成：
        1.创建一条trace轨迹
        2.构造请求参数
        3.调用agent
        4.拿到llm返回保存记录
        5.返回    TODO推测的 不一定正确 且未加入skill部分 不知道这部分需要如何配合
        :param payload:
        :param current_user:
        :return:
        """
        # 1.创造一条agent_trace轨迹 并报错到agent_trace表中
        agent_traces = AgentTrace(
            conversation_id=payload.conversation_id,
            status=AgentTraceStatus.RUNNING,
            model_name=self._setting.llm_model,
            prompt_version=self._setting.prompt_version
        )
        self._session.add(agent_traces)
        await self._session.commit()

        # 2.调用agent
        start_time = time.perf_counter()
        try:
            run_result = await self._invoke_agent(payload, current_user, agent_traces)
        except Exception as exc:
            logger.exception("Agent推理会话 %s 任务期间出错", payload.conversation_id)
            agent_traces.status = AgentTraceStatus.FAILED
            agent_traces.result = {"text": f"AI 执行出错，原因:{exc}"}
            agent_traces.latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._session.commit()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="AI智能体执行出错")

        agent_traces.status = AgentTraceStatus.COMPLETED
        agent_traces.result = run_result
        agent_traces.latency_ms = int((time.perf_counter() - start_time) * 1000)

        await self._session.commit()
        return run_result

    async def _invoke_agent(self,
                            payload: AgentRunRequest,
                            current_user: CurrentUser,
                            agent_traces: AgentTrace) -> dict[str:Any] | None:

        # 回调处理器
        call_back = UsageMetadataCallbackHandler()

        jev_input_tokens = 0
        jev_output_tokens = 0

        try:
            # 1.前置护栏校验
            appliance = payload.service_scene == "APPLIANCE_SERVICE"
            need_handoff, skill_code = False, None
            if not appliance:
                need_handoff, skill_code, jev_input_tokens, jev_output_tokens = await check_input(payload.messages)
            if not need_handoff and skill_code == "appliance_service":
                return build_request(ReplyType.ANSWER, "这类问题需要核对具体设备，请进入家电售后。",
                                     page_action={"action_code": "ENTER_APPLIANCE"})
            if need_handoff:
                return build_request(
                    ReplyType.REQUEST_HANDOFF,
                    reply_text="已收到您的诉求，正在为您转接人工客服优先处理，请稍候。",
                    summary="用户要求转接人工客服或情绪较为焦急，请人工客服优先介入处理。"
                )

            # 2.构建LangChain标准消息对象
            messages = build_messages(payload,skill_code)
            

            device = None
            query = ""
            current = payload.service_context
            if appliance:
                from atguigu.infrastructure.client import EcommerceClient
                latest = payload.messages[-1]
                previous_issue_resolved = current.get("workflow_stage") == "resolved"
                if previous_issue_resolved:
                    current = {}
                text_inputs = [m["content"].get("text", "") for m in payload.messages if m["type"] == "text"]
                query = " ".join(text_inputs).strip() or current.get("description", "")
                did = (current.get("device") or {}).get("device_id")
                if latest["type"] == "device_choice":
                    did = latest["content"].get("device_id")
                owned = await EcommerceClient(current_user.access_token).get_json("/devices")
                devices = owned["data"]
                device = next((d for d in devices if d["device_id"] == did), None)
                if latest["type"] == "text":
                    from atguigu.agent.harness.validator.appliance import serial_number_help
                    guidance = serial_number_help(latest["content"].get("text", ""), current, devices, device)
                    if guidance is not None:
                        if not current.get("description") and len(text_inputs) > 1:
                            guidance["service_context"] = {**current, "description": " ".join(text_inputs[:-1])[:500]}
                        return guidance
                mentioned = mentioned_appliance_models(query)
                if len(mentioned) == 1 and device and device["model_code"] not in mentioned and latest["type"] == "device_choice" and not text_inputs:
                    query = ""
                    mentioned = set()
                if (previous_issue_resolved and latest["type"] == "text") or (mentioned and device and (
                    device["model_code"] not in mentioned or (len(mentioned) > 1 and latest["type"] != "device_choice")
                )):
                    choices = [d for d in devices if not mentioned or d["model_code"] in mentioned]
                    reply = build_request(
                        ReplyType.CLARIFY,
                        "请确认这次咨询的设备，确认后我会继续处理。"
                        if choices else "未找到与您描述匹配的本人设备，可转人工核验。",
                        choices=choices,
                    )
                    return {**reply, "service_context": {"description": query[:500]}}
                if device and _needs_fault_description(query, latest):
                    # 设备身份已核验；不要把“序列号在哪/不知道选哪台”送去知识库，
                    # 否则会产生误导性的“没有匹配说明”。清除这类非故障描述，
                    # 让用户下一条消息成为本设备的新故障查询。
                    state = dict(current) if current.get("device") == device else {}
                    state["device"] = device
                    state["workflow_stage"] = "awaiting_fault_description"
                    state.pop("description", None)
                    state.pop("fault_code", None)
                    state.pop("chunk_id", None)
                    state.pop("pending_step", None)
                    state.pop("diagnostic_plan", None)
                    state.pop("steps", None)
                    return {
                        "reply_type": ReplyType.ANSWER,
                        "text": f"已选择 {device.get('display_name') or device['model_code']}。请描述具体故障现象，或提供设备显示的故障码（例如面板上的字母和数字组合）；如果没有故障码，也可以告诉我设备出现了什么异常。",
                        "service_context": state,
                    }
                if not did and len(devices) == 1 and latest["type"] != "device_choice":
                    device = devices[0]
                if latest["type"] == "step_feedback":
                    return build_request(ReplyType.CLARIFY, "请使用会话中的最新诊断卡。")
                if query in ("已恢复", "未恢复") and current.get("pending_step"):
                    return build_request(ReplyType.CLARIFY, "请点击当前步骤的“已恢复”或“未恢复”，以便记录本步结果。")
                messages.append(SystemMessage(content=(
                    "当前已验证为家电场景。首先调用 load_skill(appliance_service)，然后调用一次适用的业务工具。"
                    "未核属设备时只调用 list_my_devices。普通故障描述优先查询说明书。只有用户明确查询已有工单才调用工单查询工具。"
                    "最后返回 AgentOutput，appliance_card 填刚调用的工具名。不要自行提出诊断步骤或费用。"
                    + ("已核属设备：" + device["model_code"] if device else "尚未核属设备。")
                )))
                if latest["type"] == "device_choice" and query:
                    from langchain_core.messages import HumanMessage
                    messages.append(HumanMessage(content="选定设备后继续处理原问题：" + query))

            # 3.构建上下文
            context = AgentRunContext(
                access_token=current_user.access_token,
                trace_id=agent_traces.id,
                service_scene=payload.service_scene, device=device, query=query,
            )
            for attempt in range(self._setting.agent_max_attempts):
                # 4. agent运行（带纠错）
                agent_output = await self._agent.ainvoke({"messages": messages,"skill_code":skill_code  },
                                                         context=context,
                                                         config={
                                                             "callbacks": [call_back]
                                                         })
                
                # 护栏校验
                try:
                    return await self._validator.validate_agent_output(
                        skill_code=agent_output.get("skill_code"),
                        agent_output=agent_output['structured_response'],
                        trace_id=context.trace_id, context=context, previous=current
                    )
                except ValidateAgentOutError as e:
                    # 重试纠错（把执行完成的结果和【我要求你根据上一次结果的信息，给我重试】指令）
                    if attempt == self._setting.agent_max_attempts - 1:
                        raise e
                    logger.exception(f"执行Agent期间出现了护栏校验异常：{e}")
                    messages = [
                        *agent_output["messages"],
                        SystemMessage(content=f"上一次回复未通过校验：{e},请修正后重新回复")
                    ]
        except TypeSafeInternalServerError:
            return build_request(ReplyType.REQUEST_HANDOFF,
                reply_text="AI 客服判断服务暂时不可用，已为您转接人工客服。",
                summary="JEV 暂时不可用，请接续用户咨询。")
        finally:
            input_tokens, output_tokens = self._summary_tokens(call_back)
            agent_traces.input_tokens = input_tokens + jev_input_tokens
            agent_traces.output_tokens = output_tokens + jev_output_tokens

    def _summary_tokens(self, call_back: UsageMetadataCallbackHandler):
        all_model_usages: list[dict[str, Any]] = list(call_back.usage_metadata.values())
        input_tokens = sum(model_usage.get("input_tokens", 0) for model_usage in all_model_usages)
        output_tokens = sum(model_usage.get("output_tokens", 0) for model_usage in all_model_usages)
        return input_tokens, output_tokens



