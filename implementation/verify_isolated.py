"""Start disposable local services for staged checks. No shared DEMO database writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from threading import Thread
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent


def verify_secondary(database, config):
    with httpx.Client(timeout=100, trust_env=False) as client:
        token = client.post("http://127.0.0.1:18101/api/v1/auth/demo-token",
                            json={"user_id": "user_001"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token, "X-Internal-Service-Token": config["INTERNAL_SERVICE_TOKEN"]}
        for question, scene in [("你好，请用一句话打招呼。", "ECOMMERCE"),
                                ("我的洗衣机显示 E3，需要排查。", "APPLIANCE_SERVICE")]:
            cid = "secondary_" + uuid4().hex
            response = client.post("http://127.0.0.1:18102/internal/v1/agent/runs", headers=headers, json={
                "conversation_id": cid, "service_scene": scene, "history": [],
                "messages": [{"role": "USER", "type": "text", "content": {"text": question}}]})
            with psycopg.connect(database.render_as_string(hide_password=False)) as connection:
                trace = connection.execute("SELECT id,model_name,status,input_tokens,result FROM agent_traces WHERE conversation_id=%s",
                                           (cid,)).fetchone()
                calls = connection.execute("""
                    SELECT tool_call_id,tool_name,success,latency_ms FROM agent_tool_calls WHERE trace_id=%s
                """, (trace[0],)).fetchall() if trace else []
            if not response.is_success:
                diagnostic = str(trace[-1] if trace else "").lower()
                category = ("authentication" if any(x in diagnostic for x in ("401", "403", "api key")) else
                            "network" if any(x in diagnostic for x in ("timeout", "connection", "certificate")) else
                            "tool protocol" if any(x in diagnostic for x in ("400", "422", "schema", "tool_choice")) else
                            "model behavior or unknown")
                raise AssertionError(f"secondary {scene}: HTTP {response.status_code}, category={category}, trace={trace[0] if trace else None}")
            answer = response.json()
            assert trace[2] == "COMPLETED" and trace[3] > 0 and answer.get("text"), (scene, trace[:4])
            if scene == "APPLIANCE_SERVICE":
                assert any(name == "list_my_devices" and success for _, name, success, _ in calls)
                assert answer.get("choices") and answer["reply_type"] == "ANSWER"
            else:
                assert answer["reply_type"] == "ANSWER"
            print("SECONDARY", scene, trace[:4], calls, answer["reply_type"], flush=True)


def verify_tools(ai_database):
    config = dotenv_values(ROOT / "ai-service" / ".env")
    # All requests and business data belong to this disposable DEMO stack.
    with httpx.Client(timeout=120, trust_env=False) as client:
        shop = "http://127.0.0.1:18101/api/v1/"
        token = client.post(shop + "auth/demo-token", json={"user_id": "user_001"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        devices = client.get(shop + "devices", headers=headers).json()["data"]
        device = next(d for d in devices if d["model_code"] == "A-DEMO")
        before = client.get(shop + "repair-tickets", headers=headers).json()["data"]
        headers["X-Internal-Service-Token"] = config["INTERNAL_SERVICE_TOKEN"]

        def probe(case):
            question, expected, appliance = case
            cid = "check_" + uuid4().hex
            payload = {"conversation_id": cid, "messages": [{"role": "USER", "type": "text",
                       "content": {"text": question}}], "history": []}
            if appliance:
                payload.update(service_scene="APPLIANCE_SERVICE", service_context={"device": device})
            result = client.post("http://127.0.0.1:18102/internal/v1/agent/runs", headers=headers, json=payload)
            result.raise_for_status()
            answer = result.json()
            with psycopg.connect(ai_database.render_as_string(hide_password=False)) as connection:
                rows = connection.execute("""
                    SELECT t.id,c.tool_name,c.success FROM agent_traces t JOIN agent_tool_calls c ON t.id=c.trace_id
                    WHERE t.conversation_id=%s AND t.status='COMPLETED' AND t.input_tokens>0
                    """, (cid,)).fetchall()
            assert any(row[1:] == (expected, True) for row in rows), (expected, rows)
            if expected == "search_manual":
                citation = answer["citations"][0]
                assert citation["model_code"] == "A-DEMO"
                url = "http://127.0.0.1:18102/internal/v1/diagnostic-plans/" + citation["id"]
                plan = client.get(url, headers=headers, params={"device_id": device["device_id"]})
                assert plan.json()["citation"] == citation
                washer = next(d for d in devices if d["model_code"] == "W-DEMO")
                assert client.get(url, headers=headers, params={"device_id": washer["device_id"]}).status_code == 404
            elif expected == "get_device_warranty":
                assert answer["warranty"]["months"] == 24
            elif expected == "prepare_repair_preview":
                assert answer["page_action"]["action_code"] == "OPEN_REPAIR_PREVIEW"
            elif expected == "list_my_repairs":
                assert "tickets" in answer
            print("PASS", expected, rows[0][0], flush=True)

        cases = [(row["input"], row["tools"][0][0], False)
                 for row in json.loads((ROOT / "a0-commerce.json").read_text(encoding="utf8"))]
        cases.extend([("空调报 E3，原因是什么？", "search_manual", True),
                      ("这台空调的保修状态是什么？", "get_device_warranty", True),
                      ("我需要申请报修，请打开维修预览。", "prepare_repair_preview", True),
                      ("查询这台空调的已有维修工单。", "list_my_repairs", True)])
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(probe, cases))
        assert before == client.get(shop + "repair-tickets", headers=headers).json()["data"]


def run(stage):
    configured = dotenv_values(ROOT / "ai-service" / ".env")
    secondary = {}
    if stage == "secondary":
        for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
            value = os.getenv("SECONDARY_" + key) or configured.get("SECONDARY_" + key)
            if not value:
                raise SystemExit("Missing secondary configuration: SECONDARY_" + key)
            secondary[key] = value
        secondary["LLM_PROVIDER"] = "qwen"
    missing = [name for name in ("TYPESAFE_API_KEY", "LLM_API_KEY")
               if not (os.getenv(name) or configured.get(name))]
    if missing:
        raise SystemExit("Missing AI service configuration: " + ", ".join(missing))
    configs = [("ecommerce-service", "ECOM_DATABASE_URL", 18101),
               ("ai-service", "AI_DATABASE_URL", 18102), ("customer-service", "DATABASE_URL", 18100)]
    for _, _, port in configs:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    with ExitStack() as cleanup:
        for name, key, port in configs:
            directory = ROOT / name
            url = make_url(dotenv_values(directory / ".env")[key])
            assert url.host in ("127.0.0.1", "localhost")
            database = "verify_" + uuid4().hex
            admin = cleanup.enter_context(psycopg.connect(url.set(drivername="postgresql", database="postgres")
                                         .render_as_string(hide_password=False), autocommit=True))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            cleanup.callback(admin.execute, sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", API_HOST="127.0.0.1",
                       API_PORT=str(port), AI_TIMEOUT_SECONDS="90", AI_SERVICE_URL="http://127.0.0.1:18102",
                       ECOMMERCE_BASE_URL="http://127.0.0.1:18101", REDIS_URL="redis://127.0.0.1:56379/14")
            env[key] = url.set(database=database).render_as_string(hide_password=False)
            if name == "ai-service":
                env.update(secondary)
                ai_database = url.set(database=database, drivername="postgresql")
            python = os.getenv("TEST_AI_PYTHON" if name == "ai-service" else "TEST_SERVICE_PYTHON", sys.executable)
            subprocess.run([python, "-B", "migrate.py"], cwd=directory, env=env, check=True)
            args = ["-m", "atguigu.main"] if name != "ecommerce-service" else [
                "-m", "uvicorn", "ecommerce_service.main:app", "--host", "127.0.0.1", "--port", str(port)]
            capture_scope = name == "ai-service" and stage == "B"
            proc = subprocess.Popen([python, "-B", *args], cwd=directory, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE if capture_scope else subprocess.DEVNULL)
            if capture_scope:
                def print_scope(stream):
                    for line in stream:
                        if b":skill_scope trace=" in line:
                            print(line.decode("utf8", "replace").strip(), flush=True)
                Thread(target=print_scope, args=(proc.stderr,), daemon=True).start()
            def stop(process):
                process.terminate()
                process.wait(10)
            cleanup.callback(stop, proc)
            for _ in range(120):
                try:
                    r = httpx.get(f"http://127.0.0.1:{port}/openapi.json", trust_env=False)
                    if r.is_success:
                        break
                except httpx.HTTPError:
                    pass
                if proc.poll() is not None:
                    raise RuntimeError(name + " exited")
                time.sleep(.2)
            else:
                raise RuntimeError(name + " startup timed out")
        env.update(TEST_CHAT_URL="http://127.0.0.1:18100/api/v1/", TEST_SHOP_URL="http://127.0.0.1:18101/api/v1/")
        if stage == "C":
            subprocess.run([sys.executable, str(ROOT / "verify_handoff_browser.py")], env=env, check=True)
            return
        if stage == "secondary":
            verify_secondary(ai_database, configured)
            return
        if stage == "B":
            subprocess.run([sys.executable, str(ROOT / "verify_workspace.py")], env=env, check=True)
            with psycopg.connect(ai_database.render_as_string(hide_password=False)) as connection:
                for row in connection.execute("""
                    SELECT t.id,t.model_name,t.input_tokens,c.tool_call_id,c.tool_name,c.success,c.latency_ms
                    FROM agent_tool_calls c JOIN agent_traces t ON c.trace_id=t.id ORDER BY c.created_at
                """):
                    print("B_TRACE", *row)
            return
        subprocess.run([sys.executable, str(ROOT / "verify_scenes.py")], env=env, check=True)
        if stage == "A2":
            subprocess.run([sys.executable, str(ROOT / "smoke_test.py")], env=env, check=True)
            verify_tools(ai_database)
            with psycopg.connect(ai_database.render_as_string(hide_password=False)) as connection:
                evidence = connection.execute("""
                    SELECT t.id, t.model_name, t.input_tokens, c.tool_call_id, c.tool_name,
                           c.success, c.latency_ms FROM agent_traces t JOIN agent_tool_calls c ON c.trace_id=t.id
                    WHERE t.status='COMPLETED' ORDER BY t.created_at,c.created_at
                """).fetchall()
            assert any(row[2] > 0 and row[4] == "search_manual" and row[5] for row in evidence)
            for row in evidence:
                print("TRACE", *row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["A1", "A2", "B", "C", "secondary"])
    run(parser.parse_args().stage)
