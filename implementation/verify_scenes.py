"""Run against an isolated migrated three-service stack. Uses DEMO accounts."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx


def verify(base_chat, base_shop):
    client = httpx.Client(timeout=15, trust_env=False)
    def auth(uid):
        token = client.post(base_shop + "auth/demo-token", json={"user_id": uid}).json()["access_token"]
        return {"Authorization": "Bearer " + token}
    user, other = auth("user_001"), auth("user_002")
    source = uuid4().hex
    response = client.post(base_chat + "chat/messages", headers=user, json={
        "type": "text", "message_id": source, "content": {"text": "我的洗衣机显示 E3 故障，需要检修。"}})
    response.raise_for_status()
    for _ in range(120):
        messages = client.get(base_chat + "chat/history", headers=user).json()["messages"]
        if any((m["content"].get("page_action") or {}).get("source_id") == source for m in messages):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("JEV did not produce a linked appliance entry")
    entry = base_chat + "chat/appliance/entries/" + source
    assert client.post(entry, headers=other).status_code == 404
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.map(lambda _: client.post(entry, headers=user), range(2))
    one.raise_for_status()
    assert one.json() == two.json() == client.post(entry, headers=user).json()
    history = client.get(base_chat + "chat/history", params={"conversation_id": one.json()["conversation_id"]},
                         headers=user).json()
    assert len([m for m in history["messages"] if m["role"] == "USER"]) == 1
    client.close()
    print("PASS: real JEV entry, ownership, concurrent replay, one forwarded message")


if __name__ == "__main__":
    verify(os.environ["TEST_CHAT_URL"], os.environ["TEST_SHOP_URL"])
