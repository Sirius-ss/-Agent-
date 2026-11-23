import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

from atguigu.agent.llm.adapter import get_llm_client


class ModelAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_tool_call_contract(self):
        def respond(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            body = json.loads(request.content)
            self.assertEqual(body["tools"][0]["function"]["name"], "demo_lookup")
            return httpx.Response(200, json={
                "id": "demo", "object": "chat.completion", "model": "demo-model", "created": 1,
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [{
                        "id": "call_demo", "type": "function",
                        "function": {"name": "demo_lookup", "arguments": "{}"}}]}}]})

        settings = SimpleNamespace(llm_provider="qwen", llm_model="demo-model", llm_timeout_seconds=5,
            llm_api_key="test-only", llm_base_url="https://adapter.invalid/v1", llm_thinking_mode="False")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch("atguigu.agent.llm.adapter.get_settings", return_value=settings), patch(
                    "atguigu.agent.llm.adapter.ChatOpenAI",
                    side_effect=lambda **kwargs: ChatOpenAI(http_async_client=client, **kwargs)):
                model = get_llm_client()
            reply = await model.bind_tools([{
                "type": "function", "function": {"name": "demo_lookup",
                "parameters": {"type": "object", "properties": {}}}}]).ainvoke("demo")
        self.assertEqual(reply.tool_calls[0]["name"], "demo_lookup")
