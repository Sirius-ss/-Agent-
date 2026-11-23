from pathlib import Path
import unittest
from fastapi import HTTPException
from atguigu.common.event_loop import run_async
from atguigu.app.services.manuals import ingest,retrieve,parse_manual
from atguigu.infrastructure.db import async_session_factory,async_engine

ROOT=Path(__file__).resolve().parents[1]/"manuals"
def test_two_real_pdfs_have_distinct_e3():
    sets=[parse_manual(p.stem,p.name,p.read_bytes()) for p in sorted(ROOT.glob("*.pdf"))]
    assert len(sets)==2
    assert all(len(chunks)==2 and chunks[0]["fault_code"]=="E3" for chunks in sets)
    assert sets[0][0]["content"]!=sets[1][0]["content"]
    assert all(c["page_no"]==1 and len(c["user_steps"])==2 for c in [s[0] for s in sets])

def test_reimport_and_evidence():
    async def check():
        async with async_session_factory() as db:
            p=ROOT/"W-DEMO.pdf"
            for _ in range(2):
                assert await ingest(db,p.stem,p.name,p.read_bytes())==2
            with unittest.TestCase().assertRaises(HTTPException):
                await ingest(db,"A-DEMO",p.name,p.read_bytes())
            for query in ["E3","桶内积水","洗完还有积水"]:
                chunks=await retrieve(db,"W-DEMO",query)
                assert len(chunks)==1 and chunks[0]["section"].startswith("E3")
                assert chunks[0]["file_name"]=="W-DEMO.pdf"
            assert not await retrieve(db,"A-DEMO","桶内积水")
            assert not await retrieve(db,"W-DEMO","E99 桶内积水")
        await async_engine.dispose()
    run_async(check())

class ManualTests(unittest.TestCase):
    test_sources=staticmethod(test_two_real_pdfs_have_distinct_e3)
    test_search=staticmethod(test_reimport_and_evidence)
