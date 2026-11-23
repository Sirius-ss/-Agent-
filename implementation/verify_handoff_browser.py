"""Verify realtime handoff using two isolated Edge profiles."""
import json
from contextlib import ExitStack

from verify_workspace import open_browser


def main():
    with ExitStack() as stack:
        user = open_browser(stack, "user-frontend", 5173)
        staff = open_browser(stack, "admin-frontend", 5174)
        staff.command("Page.navigate", url="http://127.0.0.1:5174")
        staff.wait("!!document.querySelector('select[aria-label=切换后台账号]')")
        staff.js("const sel=document.querySelector('select[aria-label=切换后台账号]');sel.value='agent_001';sel.dispatchEvent(new Event('change'))")
        staff.wait("received.some(e=>e.event_type==='connected')")
        user.command("Page.navigate", url="http://127.0.0.1:5173/appliance")
        cid = "document.querySelector('[data-conversation]')?.dataset.conversation"
        user.wait(cid)
        conversation = json.dumps(user.js(cid))
        user.send("洗衣机 E3")
        user.button("DEMO 洗衣机 · DEMO-W1-1")
        user.button("未恢复")
        user.wait("document.querySelector('.messages').innerText.includes('请核对下一项')")
        user.send("设备正在冒烟")
        staff.wait(f"received.some(e=>e.event_type==='handoff_update' && e.conversation_id==={conversation})")
        staff.wait("!!document.querySelector('.queue-item')")
        staff.js("document.querySelector('.queue-item').click()")
        staff.wait("['W-DEMO','E3','未恢复','停止自查','维修记录'].every(x=>document.querySelector('.handoff-context')?.innerText.includes(x))")
        staff.button("接入会话")
        user.wait("document.querySelector('.service-mode').innerText==='人工服务中'")
        for page in (staff,user):
            page.js("sockets.at(-1).close()")
            page.wait("sockets.length===2 && sockets.filter(s=>s.readyState===1).length===1 && received.filter(e=>e.event_type==='connected').length===2")
            page.command("Page.reload")
            page.wait("received.some(e=>e.event_type==='connected')")
        staff.wait("!!document.querySelector('.queue-item')")
        staff.js("document.querySelector('.queue-item').click()")
        staff.wait("!!document.querySelector('.reply-box textarea:not(:disabled)')")
        user.wait("document.querySelector('.messages')?.innerText.includes('正在冒烟')")
        reply = "DEMO 客服已收到，请停止使用设备。"
        staff.js("const box=document.querySelector('.reply-box textarea');box.value=" + json.dumps(reply)
                 + ";box.dispatchEvent(new Event('input',{bubbles:true}))")
        staff.button("发送")
        user.wait("document.querySelector('.messages').innerText.includes(" + json.dumps(reply) + ")")
        staff.command("Page.enable")
        staff.js("window.confirm=()=>true")
        staff.button("结束服务")
        user.wait("document.querySelector('.service-mode').innerText==='AI 客服'")
        events = user.js("received.filter(e=>e.message_id)")
        assert [e["conversation_mode"] for e in events][-2:] == ["HUMAN","AI"]
        assert all(e["conversation_id"] == json.loads(conversation) for e in events)
        ids = user.js("Array.from(document.querySelectorAll('[data-message-id]'),e=>e.dataset.messageId)")
        assert len(ids) == len(set(ids))
        user.button("客服")
        user.wait(cid + " && " + cid + " !== " + conversation)
        assert reply not in user.js("document.querySelector('.messages').innerText")
        user.button("家电售后")
        user.wait(cid + " === " + conversation)
        user.wait("document.querySelector('.messages').innerText.includes(" + json.dumps(reply) + ")")
        assert user.js("sockets.length") == staff.js("sockets.length") == 1
        print("PASS dual Edge profiles: realtime queue, context, accept, reconnect and reload both ends, reply, resolve, ordered events, unique message IDs and scene isolation")


if __name__ == "__main__":
    main()
