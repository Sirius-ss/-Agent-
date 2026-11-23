import asyncio
from pathlib import Path
from atguigu.app.models.models import Base
from atguigu.infrastructure.db import async_engine,async_session_factory
from atguigu.app.services.manuals import ingest

async def main():
    root=Path(__file__).parent
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in (root/"migrations/001_manuals.sql").read_text().split(";"):
            if stmt.strip():
                await conn.exec_driver_sql(stmt)
    async with async_session_factory() as session:
        for pdf in sorted((root/"manuals").glob("*.pdf")):
            print(pdf.name,await ingest(session,pdf.stem,pdf.name,pdf.read_bytes()))
    await async_engine.dispose()

if __name__=="__main__":
    from atguigu.common.event_loop import run_async
    run_async(main())
