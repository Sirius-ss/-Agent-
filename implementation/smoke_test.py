"""HTTP acceptance check. Run against an isolated, fresh DEMO environment."""
import os
import time
from uuid import uuid4

import httpx

CHAT = os.getenv("TEST_CHAT_URL", "http://127.0.0.1:8000/api/v1/")
SHOP = os.getenv("TEST_SHOP_URL", "http://127.0.0.1:8001/api/v1/")
client = httpx.Client(timeout=8, trust_env=False)


def request(method, url, token=None, body=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.request(method, url, headers=headers, json=body)
    response.raise_for_status()
    return response.json()


def login(uid, role):
    return request("POST", SHOP+"auth/demo-token", body={"user_id": uid, "role": role})["access_token"]


user = login("user_001", "user")
staff = login("agent_001", "staff")
conversation = request("POST", CHAT+"chat/appliance/conversations", user)
assert conversation["service_scene"] == "APPLIANCE_SERVICE"
cid = conversation["conversation_id"]


def send(kind, **content):
    request("POST", CHAT+"chat/messages", user, dict(
        conversation_id=cid, type=kind, content=content, message_id=uuid4().hex))
    for _ in range(900):
        history = request("GET", CHAT+"chat/history?conversation_id="+cid, user)
        if history["messages"] and history["messages"][-1]["role"] == "AI":
            return history
        time.sleep(.1)
    raise AssertionError("AI reply timeout")


assert send("text", text="洗衣机 E3")["messages"][-1]["content"]["choices"]
h = send("device_choice", device_id="DEMO-W1-1")
assert h["messages"][-1]["content"]["citations"][0]["model_code"] == "W-DEMO"
for _ in range(2):
    feedback = dict(step_id=h["service_context"]["pending_step"]["id"], outcome="unresolved",
                    device_id="DEMO-W1-1", context_version=h["context_version"])
    h = send("step_feedback", **feedback)
    assert h["context_version"] == feedback["context_version"] + 1
    stale = client.post(CHAT+"chat/messages", headers={"Authorization": "Bearer "+user}, json={
        "conversation_id": cid, "message_id": uuid4().hex, "type": "step_feedback", "content": feedback})
    assert stale.status_code == 409
assert h["messages"][-1]["content"]["page_action"]["action_code"] == "OPEN_REPAIR_PREVIEW"
p = request("POST", SHOP+"repair-previews", user, dict(device_id="DEMO-W1-1", description="洗衣机 E3"))
if p["code"] == "EXISTING_TICKET":
    ticket = p["data"]
else:
    url = SHOP+"repair-previews/"+p["data"]["preview_id"]+"/confirm"
    ticket = request("POST", url, user, {"confirmed": True})["data"]
    assert request("POST", url, user, {"confirmed": True})["data"]["ticket_id"] == ticket["ticket_id"]
assert send("text", text="设备正在冒烟")["conversation_mode"] == "QUEUED"
h = next(h for h in request("GET", CHAT+"handoffs", staff) if h["conversation_id"] == cid)
url = CHAT+"handoffs/"+h["id"]
ctx = request("GET", url+"/messages", staff)["handoff_context"]
assert ctx["risk"] == "SMOKE_ACTIVE" and len(ctx["steps"]) == 2
assert ctx["tickets"][0]["ticket_id"] == ticket["ticket_id"]
request("POST", url+"/accept", staff)
request("POST", url+"/messages", staff, {"text": "已收到交接资料。"})
request("POST", url+"/resolve", staff)
print("PASS: route, device, citation, two steps, repair ticket, smoke and staff handoff")
