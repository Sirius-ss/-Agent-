from copy import deepcopy
import re

from atguigu.agent.harness.run.context import mentioned_appliance_models
from atguigu.app.services.manuals import fault_code, retrieve


def asks_for_device_identification_help(query):
    return re.search(
        r"(序列号|机身码|SN|S/N).*(哪|怎么|如何|找不到|没找到|是什)|"
        r"(哪|怎么|如何|找不到|没找到|不认识|看不懂|不知道).*(序列号|机身码|SN|S/N)|"
        r"不知道.*哪[个台一]|不确定.*哪[个台一]|分不清|怎么选|如何选|选哪个|"
        r"(?:怎么|如何)(?:看|知道|确认|判断|区分|辨认).{0,12}哪(?:个|台|一台)",
        query, re.IGNORECASE,
    )


def serial_number_help(query, state, devices, device):
    if device or not asks_for_device_identification_help(query):
        return None
    mentioned = mentioned_appliance_models(query) or mentioned_appliance_models(state.get("description") or "")
    choices = [item for item in devices if not mentioned or item["model_code"] in mentioned]
    text = ("请找机身标签上标有「序列号」「S/N」或「SN」的一串字符，再与下方设备按钮上的号码核对。"
            "洗衣机可以先看门框附近或机身侧面，空调可以先看室内机侧面或底部可见的标签。"
            "如果标签看不到，可查看原包装或保修卡上是否印有序列号。无需移机、登高或拆盖；仍找不到可点「转人工」核验。")
    if not choices:
        text += " 当前账号没有查到匹配的设备。"
    return {"reply_type": "CLARIFY", "text": text, "choices": choices}


async def validated_card(session, output, calls, context, previous):
    from atguigu.agent.harness.validator.validator import ValidateAgentOutError

    successful = [call for call in calls if call.success and call.result and call.result.get("success")]
    name = output.appliance_card
    if name is None and len({call.tool_name for call in successful}) == 1:
        name = successful[-1].tool_name
    if not context.permits_tool("appliance_service", name):
        raise ValidateAgentOutError("需要已加载技能中的本轮工具结果")
    evidence = next((c for c in reversed(successful) if c.tool_name == name), None)
    if evidence is None:
        raise ValidateAgentOutError("未找到卡片的成功执行记录")
    data = evidence.result["data"]
    state = deepcopy(previous)
    device = context.device
    if device != state.get("device"):
        state = {}
    if device:
        state["device"] = device
    if context.query and (name in ("list_my_devices", "search_manual") or not state.get("description")):
        state["description"] = context.query[:500]

    def answer(text, **fields):
        return dict(reply_type="ANSWER", text=text, service_context=state, **fields)

    if name == "list_my_devices":
        mentioned = mentioned_appliance_models(context.query)
        if mentioned:
            data = [candidate for candidate in data if candidate["model_code"] in mentioned]
        return answer("请对照序列号选择本次咨询的设备。" if data else "未找到本人平台设备，请转人工核验。", choices=data)
    did = device["device_id"]
    preview = {"action_code": "OPEN_REPAIR_PREVIEW", "device_id": did}
    if name in ("get_device_warranty", "prepare_repair_preview"):
        if data.get("device_id") != did:
            raise ValidateAgentOutError("保修依据与设备不符")
        if name == "prepare_repair_preview":
            return answer("请打开维修预览，核对设备和故障描述后再确认。", warranty=data, page_action=preview)
        return answer(data["notice"], warranty=data)
    if name == "list_my_repairs":
        if any(row["device"]["device_id"] != did for row in data):
            raise ValidateAgentOutError("工单与当前设备不符")
        return answer(f"本人该设备共有 {len(data)} 张维修工单。", tickets=data)

    model = device["model_code"]
    if evidence.arguments.get("model_code") != model or data != await retrieve(session, model, context.query):
        raise ValidateAgentOutError("说明书来源与当前型号或最新文档不符")
    state.update(fault_code=fault_code(context.query), steps=[], pending_step=None, chunk_id=None)
    state.pop("diagnostic_plan", None)
    state.pop("workflow_stage", None)
    if not data:
        return answer("当前型号说明书没有匹配片段，请补充故障码、申请维修或转人工。", page_action=preview)
    if len(data) > 1:
        return answer("有多个相关条目，请补充设备显示的故障码。")
    chunk = data[0]
    if chunk["model_code"] != model:
        raise ValidateAgentOutError("引用型号错误")
    citation = {k: chunk[k] for k in ("id", "model_code", "file_name", "page_no", "section")}
    state.update(chunk_id=chunk["id"], fault_code=chunk["fault_code"])
    state["diagnostic_plan"] = {"citation": citation, "steps": chunk["user_steps"]}
    if not chunk["user_steps"]:
        return answer(chunk["content"] + "。请申请专业维修。", citations=[citation], page_action=preview)
    step = {"id": chunk["id"] + ":0", "text": chunk["user_steps"][0]}
    state["pending_step"] = step
    return answer(chunk["content"], citations=[citation], step=step)
