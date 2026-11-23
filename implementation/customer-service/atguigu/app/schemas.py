from typing import Literal, Any

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    conversation_id: str | None = None
    message_id: str = Field(description="消息唯一id")
    type: Literal["text", "object", "device_choice", "step_feedback", "request_handoff"] = Field(description="消息内容的类型")
    content: dict[str, Any] = Field(description="消息的内容、普通文本内容、对象内容")


class CurrentUser(BaseModel):
    user_id: str
    role: Literal["user", "staff", "admin"] = "user"


class ReplyRequest(BaseModel):
    text:str