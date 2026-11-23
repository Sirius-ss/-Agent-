from typing import Any
import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from atguigu.app.dependencies import UserDep, AgentExecutorDep, TokenAuthDep, SessionDep
from atguigu.infrastructure.client import EcommerceClient
from atguigu.app.schemas import AgentRunRequest, CurrentUser

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger(__name__)
router = APIRouter(tags=["Ai Service允许路由"])


@router.get("/internal/v1/diagnostic-plans/{chunk_id}")
async def read_pending_plan(chunk_id: str, device_id: str, current_user: UserDep, _: TokenAuthDep, session: SessionDep):
    """Rehydrate a pre-integration card using its original evidence and current ownership."""
    owned = await EcommerceClient(current_user.access_token).get_json("/devices")
    device = next((row for row in owned["data"] if row["device_id"] == device_id), None)
    if device is None:
        raise HTTPException(404, "NOT_FOUND")
    row = (await session.execute(text("""
        SELECT id, model_code, file_name, page_no, section, user_steps FROM knowledge_chunks
        WHERE id=:chunk AND model_code=:model
    """), {"chunk": chunk_id, "model": device["model_code"]})).mappings().first()
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    return {"citation": {key: row[key] for key in ("id","model_code","file_name","page_no","section")},
            "steps": row["user_steps"]}


@router.post("/internal/v1/agent/runs")
async def start_run_endpoint(
        payload: AgentRunRequest,
        current_user: UserDep,
        agent_executor: AgentExecutorDep,
        _: TokenAuthDep
) -> dict[str, Any]:
    result = await agent_executor.start_run(payload, current_user)

    return result
