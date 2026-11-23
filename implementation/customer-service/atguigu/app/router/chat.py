from sqlalchemy import select, text
from atguigu.app.models.models import Conversations
import httpx
from fastapi import HTTPException
from atguigu.common.settings import get_settings
from atguigu.app.services.auth import encode_access_token
from typing import Any

from fastapi import APIRouter, Response

from atguigu.app.dependencies import ChatServiceDep, UserRoleAuthDep
from atguigu.app.schemas import ChatMessageRequest

router = APIRouter(prefix="/api/v1/chat", tags=["会话管理路由:对话、加载历史会话消息"])


@router.post("/messages")
async def chat_endpoint(
        payload: ChatMessageRequest,
        service: ChatServiceDep, # TODO调用这个接口时 service user_role 从哪里获得传入的 好像不是传入的 是依赖注入
        user_role_dep: UserRoleAuthDep
):
    await service.process_chat_message(user_role_dep.user_id, payload)


@router.get("/history")
async def get_history_endpoint(
        service: ChatServiceDep,
        user_role_dep: UserRoleAuthDep, conversation_id: str | None = None, all_scenes: bool = False) -> dict[str, Any]:
    return await service.get_chat_history(user_role_dep.user_id, conversation_id, all_scenes=all_scenes)


@router.post("/appliance/entries/{source_id}")
async def enter_appliance(source_id: str, service: ChatServiceDep, user: UserRoleAuthDep):
    return await service.enter_appliance(user.user_id, source_id)


@router.post("/appliance/conversations")
async def open_appliance(service: ChatServiceDep, user: UserRoleAuthDep, response: Response, ticket_id: str | None = None, new_repair: bool = False):
    context = None
    if ticket_id:
        if not ticket_id.startswith("RT_") or len(ticket_id)!=35:
            raise HTTPException(404,"NOT_FOUND")
        try:
            async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
                result=await client.get(get_settings().ecommerce_base_url+"/api/v1/repair-tickets/"+ticket_id,
                    headers={"Authorization":"Bearer "+encode_access_token(user.user_id)})
            if result.status_code==404:
                raise HTTPException(404,"NOT_FOUND")
            result.raise_for_status()
            ticket=result.json()["data"]
        except httpx.HTTPError as exc:
            raise HTTPException(503,"维修工单暂时无法读取") from exc
        context={"device":ticket["device"],"description":ticket["description"]}
    thread_key=ticket_id or ("repair-draft" if new_repair else "")
    if ticket_id:
        db=service._session
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                         {"key":user.user_id+"APPLIANCE_SERVICE"+thread_key})
        existing=await db.scalar(select(Conversations).where(
            Conversations.user_id==user.user_id, Conversations.service_scene=="APPLIANCE_SERVICE",
            Conversations.thread_key==ticket_id, Conversations.mode!="CLOSED"))
        if existing is None:
            legacy=await db.scalar(select(Conversations).where(
                Conversations.user_id==user.user_id, Conversations.service_scene=="APPLIANCE_SERVICE",
                Conversations.thread_key.in_(["","repair-draft"]), Conversations.mode!="CLOSED",
                Conversations.service_context["device"]["device_id"].as_string()==ticket["device"]["device_id"]
            ).order_by(Conversations.last_activity_at.desc()).limit(1).with_for_update())
            if legacy:
                legacy.thread_key=ticket_id
                await db.flush()
    conv=await service._create_or_get_conversation(user.user_id,"APPLIANCE_SERVICE",thread_key,context)
    response.status_code=201 if conv in service._session.new else 200
    await service._session.commit()
    return {"conversation_id":conv.id,"service_scene":conv.service_scene,"conversation_mode":conv.mode}
