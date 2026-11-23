"""Phase B browser acceptance, invoked by verify_isolated.py on a fresh DEMO stack."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
from contextlib import ExitStack

import httpx
from websockets.sync.client import connect


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.seq = 0

    def command(self, method, **params):
        self.seq += 1
        self.ws.send(json.dumps(dict(id=self.seq, method=method, params=params)))
        while True:
            data = json.loads(self.ws.recv(timeout=15))
            if data.get("id") == self.seq:
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data["result"]

    def js(self, expression):
        result = self.command("Runtime.evaluate", expression=expression, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"]["text"])
        return result["result"].get("value")

    def wait(self, expression, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.js(expression):
                    return
            except RuntimeError:
                pass
            time.sleep(.15)
        raise AssertionError(expression + " | " + str(self.js("document.body.innerText.slice(-1000)")))

    def button(self, label):
        expr = "Array.from(document.querySelectorAll('button')).find(b => b.offsetWidth && !b.disabled && b.textContent.trim().startsWith(" + json.dumps(label) + "))"
        self.wait("Boolean(" + expr + ")")
        self.js(expr + ".click()")

    def send(self, text):
        self.wait("!!document.querySelector('.composer textarea')")
        self.js("var box=document.querySelector('.composer textarea');box.value=" + json.dumps(text)
                + ";box.dispatchEvent(new Event('input',{bubbles:true}))")
        self.button("发送")


def open_browser(stack, frontend, web_port):
    root = Path(__file__).resolve().parent / "frontend" / frontend
    browser = Path(os.getenv("TEST_BROWSER") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    profile = Path(stack.enter_context(TemporaryDirectory(ignore_cleanup_errors=True)))
    with socket.socket() as check:
        check.bind(("127.0.0.1", web_port))
    def launch(args, **kwargs):
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        def stop():
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        stack.callback(stop)
        return proc
    # Preview the production build with the isolated API URLs embedded.
    env = dict(os.environ, VITE_CUSTOMER_SERVICE_URL="http://127.0.0.1:18100",
               VITE_ECOMMERCE_SERVICE_URL="http://127.0.0.1:18101")
    assets = profile / "dist"
    vite = [shutil.which("node"), str(root / "node_modules/vite/bin/vite.js")]
    subprocess.run([*vite, "build", "--outDir", str(assets)], cwd=root, env=env, check=True)
    launch([*vite, "preview", "--outDir", str(assets), "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], cwd=root)
    launch([str(browser), "--headless=new", "--disable-gpu", "--no-first-run", "--remote-debugging-port=0",
            "--user-data-dir=" + str(profile / "edge"), "about:blank"])
    portfile = profile / "edge/DevToolsActivePort"
    for _ in range(100):
        if portfile.exists() and portfile.read_text().strip():
            break
        time.sleep(.1)
    port = portfile.read_text().splitlines()[0]
    tabs = httpx.get(f"http://127.0.0.1:{port}/json/list", trust_env=False).json()
    ws = stack.enter_context(connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), proxy=None))
    page = Page(ws)
    page.command("Page.enable")
    page.command("Page.addScriptToEvaluateOnNewDocument", source="""
      window.sockets=[]; window.received=[];
      window.WebSocket=class extends WebSocket { constructor(...args) { super(...args);window.sockets.push(this); this.addEventListener("message",e=>window.received.push(JSON.parse(e.data))) } };
    """)
    return page


def main():
    with ExitStack() as stack:
        page = open_browser(stack, "user-frontend", 5173)
        page.command("Page.navigate", url="http://127.0.0.1:5173/chat")
        cid = "document.querySelector('[data-conversation]')?.dataset.conversation"
        page.wait(cid)
        page.send("商城有哪些洗衣机？")
        page.wait("document.querySelector('.message.ai')?.innerText.includes('洗衣机')")
        commerce = page.js(cid)
        page.button("历史")
        page.wait("document.body.innerText.includes('商城有哪些洗衣机')")
        page.button("家电售后")
        page.wait(cid)
        appliance = page.js(cid)
        assert commerce != appliance and page.js("sockets.length") == 1
        page.send("洗衣机 E3")
        page.wait("!!document.querySelector('.bubble button:not(:disabled)')")
        page.button("DEMO 洗衣机 · DEMO-W1-1")
        page.wait("document.querySelector('.messages').innerText.includes('W-DEMO.pdf')")
        page.button("未恢复")
        page.wait("document.querySelectorAll('.bubble button:disabled').length >= 2 && [...document.querySelectorAll('.bubble button')].some(b=>!b.disabled && b.textContent==='未恢复')")
        page.js("sockets.at(-1).close()")
        page.wait("sockets.length === 2 && sockets.filter(s=>s.readyState===1).length===1 && document.querySelector('.connection')?.innerText==='在线'")
        page.button("未恢复")
        page.wait("document.querySelector('.messages').innerText.includes('打开维修预览')")
        page.button("打开维修预览")
        page.wait("!!document.querySelector('[aria-label=维修工单预览]')")
        page.command("Page.reload", ignoreCache=True)
        page.wait("!!document.querySelector('[aria-label=维修工单预览]')")
        assert page.js(cid) == appliance
        page.button("确认提交维修申请")
        page.wait("location.search.includes('ticket=') && !!document.querySelector('.appliance-tools')")
        page.button("我的维修工单")
        page.wait("document.querySelector('.appliance-tools .card')?.innerText.includes('RT_')")
        ids = page.js("Array.from(document.querySelectorAll('[data-message-id]'), e=>e.dataset.messageId)")
        assert ids and len(ids) == len(set(ids))
        page.button("客服")
        page.wait(cid + " === " + json.dumps(commerce))
        page.wait("document.querySelector('.messages')?.innerText.includes('商城有哪些洗衣机')")
        assert not page.js("document.querySelector('.messages').innerText.includes('洗衣机 E3')")
        assert page.js("sockets.length") == 1
        print("PASS browser: commerce, history, two scenes, one socket, reconnect, device selection, "
              "citation, versioned steps, preview reload, explicit confirmation, tickets and message IDs")


if __name__ == "__main__":
    main()
