from typing import Literal, Any

from pydantic import BaseModel


class CurrentUser(BaseModel):
    user_id: str
    role: Literal["user", "admin"]
    access_token: str


class AgentRunRequest(BaseModel):
    conversation_id: str
    messages: list[dict[str, Any]]
    history: list[dict[str, Any]]

    service_scene: Literal["ECOMMERCE","APPLIANCE_SERVICE"] = "ECOMMERCE"
    service_context: dict = {}
    context_version: int = 0
