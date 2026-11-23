"""Read-only tools. Identity, device, model and user query come from the run."""
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from atguigu.agent.harness.run.context import AgentRunContext
from atguigu.agent.harness.tools.executor import tool_executor
from atguigu.app.services.manuals import retrieve
from atguigu.infrastructure.client import EcommerceClient
from atguigu.infrastructure.db import async_session_factory


@tool
async def list_my_devices(runtime: ToolRuntime[AgentRunContext]) -> str:
    """读取本人购买的设备供用户选择。"""
    client = EcommerceClient(runtime.context.access_token)
    return await tool_executor.executor_tool(runtime, "list_my_devices", {}, operator=lambda: client.get_json("/devices"))


@tool
async def search_manual(runtime: ToolRuntime[AgentRunContext]) -> str:
    """按已验证设备型号及用户原话搜索故障码或症状，获取可引用的说明书片段。"""
    async def lookup():
        async with async_session_factory() as session:
            rows = await retrieve(session, runtime.context.device["model_code"], runtime.context.query)
        return {"success": True, "code": "OK", "message": "", "data": rows}
    return await tool_executor.executor_tool(runtime, "search_manual", {
        "model_code": (runtime.context.device or {}).get("model_code"), "query": runtime.context.query}, operator=lookup)


@tool
async def get_device_warranty(runtime: ToolRuntime[AgentRunContext]) -> str:
    """读取已选择设备的确定性保修计算结果。"""
    return await device_operation(runtime, "get_device_warranty")


@tool
async def prepare_repair_preview(runtime: ToolRuntime[AgentRunContext]) -> str:
    """查询设备的保修提示以展示打开维修预览入口。用户自行核对确认。"""
    return await device_operation(runtime, "prepare_repair_preview")


@tool
async def list_my_repairs(runtime: ToolRuntime[AgentRunContext]) -> str:
    """查询本人为当前设备提交的维修工单。"""
    return await device_operation(runtime, "list_my_repairs")


async def device_operation(runtime, name):
    did = (runtime.context.device or {}).get("device_id")
    client = EcommerceClient(runtime.context.access_token)
    async def read():
        if name == "list_my_repairs":
            return await client.get_json("/repair-tickets", {"device_id": did})
        return await client.get_json(f"/devices/{did}/warranty")
    return await tool_executor.executor_tool(runtime, name, {"device_id": did}, operator=read)
