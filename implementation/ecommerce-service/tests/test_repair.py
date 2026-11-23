from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ecommerce_service.main import app
from ecommerce_service.database import Base, engine, get_db
from ecommerce_service.seed import seed_demo_data
from ecommerce_service.appliance_seed import seed_appliances

@pytest.fixture(scope="module")
def api():
    schema = "test_repair_" + uuid4().hex
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA "+schema)
    test_engine = create_engine(engine.url, connect_args={"options":"-c search_path="+schema})
    sessions = sessionmaker(test_engine)
    def dependency():
        with sessions() as session:
            yield session
    try:
        with test_engine.begin() as conn:
            Base.metadata.create_all(conn)
            conn.exec_driver_sql((Path(__file__).resolve().parents[1]/"migrations/001_appliance.sql").read_text())
        with sessions() as session:
            seed_demo_data(session)
            seed_appliances(session)
            seed_appliances(session)
        app.dependency_overrides[get_db] = dependency
        client=TestClient(app)
        def auth(uid):
            token=client.post("/api/v1/auth/demo-token",json={"user_id":uid}).json()["access_token"]
            return {"Authorization":"Bearer "+token}
        yield client, auth("user_001"),auth("user_002")
    finally:
        app.dependency_overrides.pop(get_db,None)
        test_engine.dispose()
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA "+schema+" CASCADE")

def test_owner_and_units(api):
    c,a,b=api
    data=c.get("/api/v1/devices",headers=a).json()["data"]
    assert len(data)==3 and len({d["serial_no"] for d in data})==3
    assert c.get("/api/v1/devices/DEMO-W1-1/warranty",headers=b).status_code==404
    assert c.get("/api/v1/devices").status_code==401

def test_confirm_races(api):
    c,a,b=api
    def preview():
        return c.post("/api/v1/repair-previews",headers=a,json={"device_id":"DEMO-W1-1","description":"E3"}).json()["data"]["preview_id"]
    p,q=preview(),preview()
    url=lambda key: f"/api/v1/repair-previews/{key}/confirm"
    assert c.post(url(p),headers=a,json={}).status_code==422
    assert c.post(url(p),headers=b,json={"confirmed":True}).status_code==404
    assert c.get("/api/v1/repair-tickets",headers=a).json()["data"]==[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda key:c.post(url(key),headers=a,json={"confirmed":True}),[p,q,p,q]))
    assert sorted(r.status_code for r in results)==[200,200,200,201]
    ids={r.json()["data"]["ticket_id"] for r in results}
    assert len(ids)==1
    assert c.get("/api/v1/repair-tickets/"+ids.pop(),headers=b).status_code==404
    assert len(c.get("/api/v1/repair-tickets",headers=a).json()["data"])==1

def test_atomic_replace(api):
    c,a,_=api
    body={"device_id":"DEMO-W1-2","description":"E3"}
    old=c.post("/api/v1/repair-previews",headers=a,json=body).json()["data"]
    assert old["warranty"]["status"]=="UNVERIFIED"
    body["replaces_preview_id"]=old["preview_id"]
    assert c.post("/api/v1/repair-previews",headers=a,json={**body,"device_id":"missing"}).status_code==404
    new=c.post("/api/v1/repair-previews",headers=a,json=body)
    assert new.status_code==201
    assert c.post("/api/v1/repair-previews/"+old["preview_id"]+"/confirm",headers=a,json={"confirmed":True}).status_code==409
