import re
from copy import deepcopy
from fastapi import HTTPException
from sqlalchemy import select
from atguigu.app.models.models import Handoff
from atguigu.app.models.enums import ConversationMode, HandoffStatus

def smoke(text):
    for clause in re.split(r"[，。；！？,;!?]",text):
        for match in re.finditer("正在冒烟",clause):
            before=clause[:match.start()]
            if not re.search(r"(如果|假如|假设|要是|是否|没有|并非|不是|并未|未见|没在)[^，。；！？]*$",before):
                return True
    return False

async def handoff(chat,conversation,reason,description,risk=False):
    ctx=deepcopy(conversation.service_context or {})
    ctx["reason"]=reason
    ctx["user_report"]=description
    ctx.setdefault("description",description)
    code=re.search(r"[A-Za-z]+\d+",description)
    if code:
        ctx["fault_code"]=code[0].upper()
    if risk:
        ctx["risk"]="SMOKE_ACTIVE"
    conversation.service_context=ctx
    conversation.context_version+=1
    if conversation.mode==ConversationMode.AI:
        conversation.mode=ConversationMode.QUEUED
        chat._realtime_services.add_handoff(conversation,reason)
    else:
        existing=await chat._session.scalar(select(Handoff).where(Handoff.conversation_id==conversation.id,
                      Handoff.status.in_([HandoffStatus.WAITING,HandoffStatus.ACTIVE])).with_for_update())
        if existing:
            existing.context_snapshot=ctx
            existing.summary=reason
    content="请停止使用设备。" if risk else ""
    content+="人工客服正在接待。" if conversation.mode==ConversationMode.HUMAN else "已为您转接人工客服。"
    chat._save_ai_reply({"text":content},conversation)
