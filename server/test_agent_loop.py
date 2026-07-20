import unittest

from server.agent_loop import AgentLoopDependencies, SingleAgentLoop
from server.local_extensions import LocalTool, LocalToolRegistry


class SingleAgentLoopTests(unittest.TestCase):
    def make_loop(self, model_events):
        calls = iter(model_events)
        registry = LocalToolRegistry([
            LocalTool(
                "status",
                "状态",
                "读取状态",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                execute_fn=lambda _args: {"service": "ok"},
            )
        ])
        return SingleAgentLoop(AgentLoopDependencies(
            load_messages=lambda _thread_id: [{"role": "user", "content": "测试"}],
            stream_model=lambda _messages, _tools, _context: next(calls),
            tools=registry,
            new_id=lambda _prefix: "generated_call",
            summarize_tool_result=lambda result: result["service"],
        ))

    def test_executes_authorized_tool_and_returns_final_stream(self):
        loop = self.make_loop([
            iter([{"type": "done", "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_1", "function": {"name": "status", "arguments": "{}"}}],
            }}]),
            iter([
                {"type": "content", "text": "完成"},
                {"type": "done", "message": {"role": "assistant", "content": "完成", "tool_calls": None}},
            ]),
        ])
        audit_events = []

        output = "".join(loop.stream(
            "thread_1",
            "system",
            {"allowed_tool_ids": ["status"], "max_tool_steps": 2},
            lambda event_type, payload: audit_events.append((event_type, payload)),
        ))

        self.assertEqual(output, "完成")
        self.assertEqual([event_type for event_type, _payload in audit_events], ["model_call", "tool_call", "tool_result", "model_call"])
        self.assertEqual(audit_events[1][1]["tool_call_id"], audit_events[2][1]["tool_call_id"])

    def test_rejects_empty_terminal_response(self):
        loop = self.make_loop([
            iter([{"type": "done", "message": {"role": "assistant", "content": "", "tool_calls": None}}]),
        ])

        with self.assertRaisesRegex(RuntimeError, "模型返回为空"):
            list(loop.stream("thread_1", "system", {"allowed_tool_ids": [], "max_tool_steps": 1}, lambda *_args: None))

    def test_strict_budget_rejects_extra_calls_in_one_model_response(self):
        loop = self.make_loop([
            iter([{"type": "done", "message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "function": {"name": "status", "arguments": "{}"}},
                {"id": "call_2", "function": {"name": "status", "arguments": "{\"x\": 1}"}},
            ]}}]),
            iter([{"type": "content", "text": "完成"}, {"type": "done", "message": {"role": "assistant", "content": "完成", "tool_calls": None}}]),
        ])
        events = []
        self.assertEqual("".join(loop.stream("thread_1", "system", {"allowed_tool_ids": ["status"], "max_tool_steps": 1, "strict_tool_budget": True}, lambda kind, payload: events.append((kind, payload)))), "完成")
        self.assertEqual(sum(kind == "tool_result" for kind, _ in events), 1)
        self.assertTrue(any(kind == "tool_error" and payload.get("budget_exhausted") for kind, payload in events))

    def test_validated_initial_action_uses_the_same_authorized_tool_path(self):
        loop = self.make_loop([
            iter([{"type": "content", "text": "完成"}, {"type": "done", "message": {"role": "assistant", "content": "完成", "tool_calls": None}}]),
        ])
        events = []
        output = "".join(loop.stream("thread_1", "system", {
            "allowed_tool_ids": ["status"], "max_tool_steps": 1,
            "initial_tool_action": {"type": "use_tool", "tool_id": "status", "arguments": {}},
        }, lambda kind, payload: events.append((kind, payload))))
        self.assertEqual(output, "完成")
        self.assertEqual([kind for kind, _ in events], ["tool_call", "tool_result", "model_call"])

    def test_rejects_same_tool_action_without_new_evidence(self):
        loop = self.make_loop([
            iter([{"type": "done", "message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "function": {"name": "status", "arguments": "{}"}}]}}]),
            iter([{"type": "done", "message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call_2", "function": {"name": "status", "arguments": "{}"}}]}}]),
            iter([{"type": "content", "text": "完成"}, {"type": "done", "message": {"role": "assistant", "content": "完成", "tool_calls": None}}]),
        ])
        events = []
        self.assertEqual("".join(loop.stream("thread_1", "system", {"allowed_tool_ids": ["status"], "max_tool_steps": 3}, lambda kind, payload: events.append((kind, payload)))), "完成")
        self.assertEqual(sum(kind == "tool_result" for kind, _ in events), 1)
        self.assertTrue(any(kind == "tool_error" and payload.get("duplicate_action") for kind, payload in events))


if __name__ == "__main__":
    unittest.main()
