import json
import base64
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote
from http.server import ThreadingHTTPServer
from pathlib import Path

from server import app


class AgentPlatformApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app.DB_PATH
        self.original_api_key = app.DEEPSEEK_API_KEY
        self.original_base_url = app.DEEPSEEK_BASE_URL
        app.DB_PATH = Path(self.temp_dir.name) / "agent_platform.db"
        app.DEEPSEEK_API_KEY = ""
        app.init_db()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.AgentPlatformHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.login()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        app.DB_PATH = self.original_db_path
        app.DEEPSEEK_API_KEY = self.original_api_key
        app.DEEPSEEK_BASE_URL = self.original_base_url
        self.temp_dir.cleanup()

    def request_json(self, path, payload=None, token=None, method=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method or ("POST" if data else "GET"))
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def chat(self, payload):
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            raw = response.read().decode("utf-8")
        return [self.parse_event(event) for event in raw.strip().split("\n\n") if event]

    @staticmethod
    def parse_event(raw):
        lines = raw.splitlines()
        event = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        return {"event": event, "data": json.loads(data)}

    def login(self):
        result = self.request_json(
            "/api/login",
            {"email": "admin@example.com", "password": "admin123"},
        )
        return result["token"]

    def test_multiple_turns_complete_and_history_is_stable(self):
        first_events = self.chat({"thread_id": "", "content": "第一轮"})
        self.assertEqual(first_events[-1]["event"], "done")
        thread_id = next(event["data"]["thread_id"] for event in first_events if event["event"] == "meta")

        second_events = self.chat({"thread_id": thread_id, "content": "第二轮"})
        self.assertEqual(second_events[-1]["event"], "done")

        history = self.request_json(f"/api/threads/{thread_id}", token=self.token)
        self.assertEqual([message["role"] for message in history["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertEqual([message["content"] for message in history["messages"]][::2], ["第一轮", "第二轮"])

        runs = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"]
        self.assertEqual(len(runs), 2)
        run_detail = self.request_json(f"/api/runs/{runs[0]['id']}", token=self.token)
        self.assertEqual(
            [event["type"] for event in run_detail["events"]],
            ["started", "execution_context", "skill_routed", "plan_created", "model_request", "completed"],
        )
        self.assertEqual(json.loads(run_detail["run"]["skill_snapshot"])[0]["id"], "general_assistant")
        context = json.loads(run_detail["run"]["execution_context"])
        self.assertEqual(context["model"], app.DEEPSEEK_MODEL)
        self.assertEqual(context["allowed_tool_ids"], [])
        self.assertEqual(run_detail["steps"][0]["status"], "completed")

        renamed = self.request_json(f"/api/threads/{thread_id}", {"title": "已重命名"}, self.token, method="PATCH")
        self.assertEqual(renamed["thread"]["title"], "已重命名")

        self.request_json("/api/skills/code_assistant", {"enabled": True}, self.token, method="PATCH")
        selected = self.request_json(
            f"/api/threads/{thread_id}/skills", {"skill_ids": ["code_assistant"]}, self.token, method="PATCH"
        )
        self.assertEqual(selected["skill_ids"], ["code_assistant"])
        self.chat({"thread_id": thread_id, "content": "第三轮", "skill_ids": ["code_assistant"]})
        latest_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        self.assertEqual([skill["id"] for skill in json.loads(latest_run["skill_snapshot"])], ["code_assistant"])

        self.request_json("/api/skills/code_assistant", {"enabled": False}, self.token, method="PATCH")
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self.chat({"thread_id": thread_id, "content": "不能使用关闭技能", "skill_ids": ["code_assistant"]})
        self.assertEqual(rejected.exception.code, 400)
        self.chat({"thread_id": thread_id, "content": "第四轮"})
        disabled_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        self.assertNotIn("code_assistant", [skill["id"] for skill in json.loads(disabled_run["skill_snapshot"])])

    def test_local_tool_execution_is_bounded_and_audited(self):
        events = self.chat({"thread_id": "", "content": "请告诉我平台状态"})
        self.assertEqual(events[-1]["event"], "done")
        self.assertIn("平台状态", "".join(event["data"].get("content", "") for event in events))
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        detail = self.request_json(f"/api/runs/{run['id']}", token=self.token)
        event_types = [event["type"] for event in detail["events"]]
        self.assertIn("tool_call", event_types)
        self.assertIn("tool_result", event_types)

    def test_high_value_task_records_reflection_without_private_reasoning(self):
        events = self.chat({"thread_id": "", "content": "请写一份产品调研方案"})
        self.assertEqual(events[-1]["event"], "done")
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        detail = self.request_json(f"/api/runs/{run['id']}", token=self.token)
        reflection = json.loads(detail["run"]["reflection_snapshot"])
        self.assertTrue(reflection["applied"])
        self.assertNotIn("reasoning", reflection)
        self.assertIn("reflection_started", [event["type"] for event in detail["events"]])
        self.assertIn("reflection_completed", [event["type"] for event in detail["events"]])

    def test_automatic_model_routing_and_minimal_tool_scope(self):
        events = self.chat({"thread_id": "", "content": "请制定一个完整的产品竞品调研方案"})
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        context = json.loads(run["execution_context"])
        self.assertEqual(run["model"], app.DEEPSEEK_DEEP_MODEL)
        self.assertEqual(context["task_tier"], "deep")
        self.assertEqual(context["allowed_tool_ids"], [])

        tool_events = self.chat({"thread_id": thread_id, "content": "请告诉我平台状态"})
        self.assertEqual(tool_events[-1]["event"], "done")
        tool_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        tool_context = json.loads(tool_run["execution_context"])
        self.assertEqual(tool_run["model"], app.DEEPSEEK_MODEL)
        self.assertEqual(tool_context["allowed_tool_ids"], ["platform_status"])

    def test_task_mode_override_and_local_metrics(self):
        events = self.chat({"thread_id": "", "content": "请分析一个产品方案", "task_mode": "quick"})
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        context = json.loads(run["execution_context"])
        self.assertEqual(context["task_tier"], "quick")
        self.assertFalse(context["quality_check"])
        self.assertGreater(run["input_tokens_estimate"], 0)
        self.assertGreater(run["output_tokens_estimate"], 0)

        metrics = self.request_json("/api/metrics", token=self.token)
        self.assertGreaterEqual(metrics["sample_size"], 1)
        self.assertIn("quick", metrics["tiers"])

    def test_task_router_keeps_structured_short_tasks_out_of_quick_mode(self):
        self.assertEqual(app.infer_task_profile("请改写这段通知")["task_tier"], "standard")
        self.assertEqual(app.infer_task_profile("分析这段代码")["task_tier"], "standard")
        self.assertEqual(app.infer_task_profile("补充下一步待办")["task_tier"], "standard")

    def test_local_knowledge_upload_retrieval_citation_and_delete(self):
        source = "# 产品资料\n\n北极星指标是每周完成首次核心任务的活跃用户数。"
        uploaded = self.request_json(
            "/api/knowledge",
            {
                "filename": "product.md",
                "mime_type": "text/markdown",
                "content_base64": base64.b64encode(source.encode("utf-8")).decode("ascii"),
            },
            self.token,
        )
        document_id = uploaded["document"]["id"]
        documents = self.request_json("/api/knowledge", token=self.token)["documents"]
        self.assertEqual(documents[0]["id"], document_id)
        results = self.request_json(f"/api/knowledge/search?query={quote('北极星指标')}", token=self.token)["results"]
        self.assertEqual(results[0]["filename"], "product.md")

        events = self.chat({"thread_id": "", "content": "请说明北极星指标"})
        answer = "".join(event["data"].get("content", "") for event in events)
        self.assertIn("参考资料：product.md", answer)
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        context = json.loads(run["execution_context"])
        self.assertEqual(context["knowledge_refs"][0]["filename"], "product.md")

        self.request_json(f"/api/knowledge/{document_id}", token=self.token, method="DELETE")
        self.assertEqual(self.request_json(f"/api/knowledge/search?query={quote('北极星指标')}", token=self.token)["results"], [])

    def test_failed_run_can_retry_without_duplicate_user_message(self):
        app.DEEPSEEK_API_KEY = "test"
        app.DEEPSEEK_BASE_URL = self.base_url
        failed_events = self.chat({"thread_id": "", "content": "请重试"})
        self.assertEqual(failed_events[-1]["event"], "error")
        thread_id = next(event["data"]["thread_id"] for event in failed_events if event["event"] == "meta")

        app.DEEPSEEK_API_KEY = ""
        retry_events = self.chat({"thread_id": thread_id, "content": "请重试", "retry": True})
        self.assertEqual(retry_events[-1]["event"], "done")

        history = self.request_json(f"/api/threads/{thread_id}", token=self.token)
        self.assertEqual([message["role"] for message in history["messages"]], ["user", "assistant"])
        self.assertEqual(history["messages"][0]["content"], "请重试")


if __name__ == "__main__":
    unittest.main()
