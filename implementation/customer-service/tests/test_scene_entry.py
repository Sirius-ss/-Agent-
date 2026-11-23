import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atguigu.app.models.models import Base, ConversationTurn, Message
from atguigu.app.services.chat import ChatService
from atguigu.common.event_loop import run_async
from atguigu.common.settings import get_settings


def test_concurrent_verified_entry_and_safety():
    run_async(exercise_entry())


async def exercise_entry():
    url = get_settings().database_url
    schema = "test_entry_" + uuid4().hex
    control = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"options": "-c search_path=" + schema})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with control.begin() as connection:
        await connection.execute(text("CREATE SCHEMA " + schema))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            service = ChatService(session)
            source = await service._create_or_get_conversation("alice")
            await session.flush()
            for key, question in [("normal", "洗衣机故障"), ("smoke", "设备正在冒烟"), ("no_offer", "订单")]:
                session.add(Message(message_id=key, role="USER", message_type="text",
                                    conversation_id=source.id, content={"text": question}))
                if key != "no_offer":
                    session.add(Message(message_id="offer_" + key, role="AI", message_type="text",
                                        conversation_id=source.id, content={"page_action": {
                                            "action_code": "ENTER_APPLIANCE", "source_id": key}}))
            await session.commit()

        async def enter(owner, key):
            async with sessions() as session:
                return await ChatService(session).enter_appliance(owner, key)
        for owner, key, status in [("bob", "normal", 404), ("alice", "no_offer", 409)]:
            with pytest.raises(HTTPException) as failed:
                await enter(owner, key)
            assert failed.value.status_code == status
        first, second = await asyncio.gather(enter("alice", "normal"), enter("alice", "normal"))
        assert first == second == await enter("alice", "normal")
        urgent = await enter("alice", "smoke")
        async with sessions() as session:
            assert await session.scalar(select(func.count(Message.id)).where(
                Message.conversation_id == first["conversation_id"])) == 1
            assert await session.scalar(select(func.count(ConversationTurn.id))) == 1
            history = await ChatService(session).get_chat_history("alice", urgent["conversation_id"])
            assert history["conversation_mode"] == "QUEUED"
            assert history["service_context"]["risk"] == "SMOKE_ACTIVE"
    finally:
        await engine.dispose()
        async with control.begin() as connection:
            await connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        await control.dispose()
