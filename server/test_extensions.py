import unittest

from server import app
from server.local_extensions import CallableModelAdapter, LocalTool, LocalToolRegistry, LocalWorkflowRunner


class LocalExtensionTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifiable(self):
        password_hash = app.hash_password("local-test-password")
        self.assertTrue(password_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(app.verify_password("local-test-password", password_hash))
        self.assertFalse(app.verify_password("incorrect", password_hash))

    def test_local_tool_registry_exposes_read_only_metadata(self):
        tools = LocalToolRegistry([LocalTool("health", "健康检查", "读取状态")]).list()
        self.assertEqual(tools[0]["risk"], "read_only")
        self.assertTrue(tools[0]["enabled"])

    def test_tool_registry_validates_authorization_and_arguments(self):
        registry = LocalToolRegistry([
            LocalTool(
                "echo",
                "回显",
                "返回文本",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
                execute_fn=lambda arguments: {"text": arguments["text"]},
            )
        ])
        self.assertEqual(registry.execute("echo", {"text": "ok"}, {"echo"}), {"text": "ok"})
        with self.assertRaises(ValueError):
            registry.execute("echo", {}, {"echo"})
        with self.assertRaises(ValueError):
            registry.execute("echo", {"text": "ok"}, set())

    def test_workflow_and_model_adapter_delegate_without_external_services(self):
        workflow = LocalWorkflowRunner()
        self.assertEqual(workflow.run(1, [lambda value: value + 2, lambda value: value * 3]), 9)
        adapter = CallableModelAdapter("test", lambda _system, _messages: iter(["a", "b"]))
        self.assertEqual("".join(adapter.stream("", [])), "ab")


if __name__ == "__main__":
    unittest.main()
