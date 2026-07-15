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
        self.assertEqual([event_type for event_type, _payload in audit_events], ["tool_call", "tool_result"])
        self.assertEqual(audit_events[0][1]["tool_call_id"], audit_events[1][1]["tool_call_id"])

    def test_rejects_empty_terminal_response(self):
        loop = self.make_loop([
            iter([{"type": "done", "message": {"role": "assistant", "content": "", "tool_calls": None}}]),
        ])

        with self.assertRaisesRegex(RuntimeError, "模型返回为空"):
            list(loop.stream("thread_1", "system", {"allowed_tool_ids": [], "max_tool_steps": 1}, lambda *_args: None))


if __name__ == "__main__":
    unittest.main()
