import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from atguigu.agent.harness.tools.definitions import load_skill
from atguigu.agent.harness.tools.executor import ToolExecutor
from atguigu.agent.harness.run.context import AgentRunContext
from atguigu.agent.harness.validator.appliance import validated_card
from atguigu.agent.harness.validator.validator import ValidateAgentOutError


class ScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_cross_scene_load_keeps_skill(self):
        for scene, skill in [("ECOMMERCE", "appliance_service"), ("APPLIANCE_SERVICE", "order_service")]:
            runtime = SimpleNamespace(context=SimpleNamespace(service_scene=scene), tool_call_id="test")
            result = await load_skill.coroutine(runtime, skill)
            self.assertNotIn("skill_code", result.update)

    async def test_hidden_tool_does_not_execute(self):
        executor = ToolExecutor()
        operator = AsyncMock()
        runtime = SimpleNamespace(context=AgentRunContext("test", "token", "APPLIANCE_SERVICE"),
                                  state={"skill_code": "order_service"}, tool_call_id="test")
        with patch.object(executor, "_save_tool_result", new_callable=AsyncMock) as record:
            await executor.executor_tool(runtime, "list_orders", {}, operator=operator)
            self.assertFalse(record.await_args.kwargs["success"])
        operator.assert_not_awaited()

    async def test_evidence_scope_and_missing_document(self):
        device = {"device_id": "demo", "model_code": "W-DEMO"}
        context = AgentRunContext("test", "token", "APPLIANCE_SERVICE", device, "E3")
        output = SimpleNamespace(appliance_card="search_manual")
        with self.assertRaises(ValidateAgentOutError):
            await validated_card(None, output, [], context, {})
        evidence = SimpleNamespace(tool_name="search_manual", success=True,
                                   result={"success": True, "data": []}, arguments={"model_code": "A-DEMO"})
        with self.assertRaises(ValidateAgentOutError):
            await validated_card(None, output, [evidence], context, {})
        evidence.arguments["model_code"] = "W-DEMO"
        with patch("atguigu.agent.harness.validator.appliance.retrieve", new_callable=AsyncMock, return_value=[]):
            card = await validated_card(None, output, [evidence], context, {})
            self.assertNotIn("citations", card)
            self.assertIn("没有匹配片段", card["text"])
            evidence.result["data"] = [{"model_code": "W-DEMO", "id": "invented"}]
            with self.assertRaises(ValidateAgentOutError):
                await validated_card(None, output, [evidence], context, {})
