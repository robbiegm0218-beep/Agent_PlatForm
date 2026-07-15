import json
import base64
import io
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from urllib.parse import quote
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from server import app
from server.provider_config import ProviderConfig


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

    def request_json(self, path, payload=None, token=None, method=None, timeout=3):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method or ("POST" if data else "GET"))
        with urllib.request.urlopen(request, timeout=timeout) as response:
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

    def download_artifact(self, artifact_id):
        request = urllib.request.Request(
            f"{self.base_url}/api/artifacts/{artifact_id}/download",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), response.headers.get_content_type()

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

    def test_health_reports_database_readiness_without_login(self):
        health = self.request_json("/api/health", method="GET")

        self.assertTrue(health["ok"])
        self.assertTrue(health["database_ready"])
        self.assertEqual(health["database"], "sqlite")
        self.assertEqual(health["environment"], "development")

    def test_models_expose_provider_neutral_capabilities(self):
        result = self.request_json("/api/models", token=self.token)
        model = next(item for item in result["models"] if item["id"] == "deepseek-v4-flash")
        self.assertEqual(model["provider_id"], "deepseek")
        self.assertTrue(model["capabilities"]["streaming"])
        self.assertTrue(model["capabilities"]["tool_calling"])
        self.assertFalse(model["capabilities"]["vision"])

    def test_openai_compatible_model_uses_its_own_environment_key(self):
        provider_config = ProviderConfig(
            provider_id="custom",
            display_name="Custom",
            api_key_env="CUSTOM_API_KEY",
            base_url="https://models.example.test/v1",
            models=("custom-chat",),
        )
        with patch.dict(app.EXTERNAL_MODEL_CONFIGS, {"custom-chat": provider_config}), patch.dict(
            app.os.environ, {"CUSTOM_API_KEY": "test-key"}, clear=False
        ), patch.object(app, "DeepSeekProvider") as provider_class:
            provider_class.return_value.complete.return_value = {"content": "ok"}
            result = app.deepseek_chat([], [], "custom-chat", 128)
            config = provider_class.call_args.args[0]

        self.assertEqual(result, {"content": "ok"})
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.base_url, "https://models.example.test/v1")
        self.assertEqual(config.provider_name, "Custom")

    def test_unconfigured_external_model_does_not_claim_connection_and_tool_route_falls_back(self):
        provider_config = ProviderConfig("custom", "Custom", "CUSTOM_API_KEY", "https://models.example.test/v1", ("custom-chat",))
        custom_profile = {
            "name": "Custom · custom-chat",
            "tier": "standard",
            "supports_tools": False,
            "max_output_tokens": {"quick": 128, "standard": 256, "deep": 512},
            "provider_id": "custom",
        }
        with patch.dict(app.EXTERNAL_MODEL_CONFIGS, {"custom-chat": provider_config}), patch.dict(
            app.MODEL_CATALOG, {"custom-chat": custom_profile}
        ), patch.dict(app.os.environ, {"CUSTOM_API_KEY": ""}, clear=False):
            self.assertFalse(app.model_is_configured("custom-chat"))
            route = app.infer_task_profile("请搜索本地文件", requested_model="custom-chat")

        self.assertEqual(route["model"], app.DEEPSEEK_MODEL)
        self.assertEqual(route["route"], "fallback")

    def test_thread_context_includes_audited_web_sources(self):
        events = self.chat({"thread_id": "", "content": "你好"})
        meta = next(event["data"] for event in events if event["event"] == "meta")
        with app.db() as conn:
            app.append_run_event(conn, meta["run_id"], "tool_result", {
                "tool_id": "web_search",
                "tool_name": "网页检索",
                "sources": [{
                    "kind": "web",
                    "title": "Agent 平台文档",
                    "url": "https://example.test/agent",
                    "excerpt": "受控检索结果",
                }],
            })
        context = self.request_json(f"/api/threads/{meta['thread_id']}/context", token=self.token)
        source = next(item for item in context["sources"] if item["kind"] == "web")
        self.assertEqual(source["title"], "Agent 平台文档")
        self.assertEqual(source["url"], "https://example.test/agent")

    def test_skill_zip_upload_versions_and_restore(self):
        original_skills_dir = app.SKILLS_DIR
        original_history_dir = app.SKILL_HISTORY_DIR
        original_package_dir = app.SKILL_PACKAGE_DIR
        original_skills = app.SKILLS
        app.SKILLS_DIR = Path(self.temp_dir.name) / "skills"
        app.SKILL_HISTORY_DIR = Path(self.temp_dir.name) / "history"
        app.SKILL_PACKAGE_DIR = Path(self.temp_dir.name) / "packages"
        try:
            bundle = io.BytesIO()
            skill = {
                "id": "bundle_skill", "name": "Bundle", "description": "测试", "version": "1.0.0",
                "prompt": "只输出测试", "input_limit": 1200, "default_enabled": False, "status": "enabled",
            }
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("skill.json", json.dumps(skill))
            created = self.request_json("/api/skills", {"bundle_base64": base64.b64encode(bundle.getvalue()).decode()}, self.token)
            self.assertEqual(created["skill"]["id"], "bundle_skill")

            skill["version"] = "2.0.0"
            skill["prompt"] = "新版本"
            self.request_json("/api/skills/bundle_skill", {"skill": skill}, self.token, method="PATCH")
            versions = self.request_json("/api/skills/bundle_skill/versions", token=self.token)["versions"]
            self.assertEqual(versions[0]["version"], "1.0.0")
            restored = self.request_json("/api/skills/bundle_skill/restore", {"archive": versions[0]["archive"]}, self.token)
            self.assertEqual(restored["skill"]["version"], "1.0.0")
        finally:
            app.SKILLS_DIR = original_skills_dir
            app.SKILL_HISTORY_DIR = original_history_dir
            app.SKILL_PACKAGE_DIR = original_package_dir
            app.SKILLS = original_skills

    def test_standard_skill_package_accepts_wrapped_resources_without_executing_scripts(self):
        original_skills_dir = app.SKILLS_DIR
        original_package_dir = app.SKILL_PACKAGE_DIR
        original_skills = app.SKILLS
        app.SKILLS_DIR = Path(self.temp_dir.name) / "skills"
        app.SKILL_PACKAGE_DIR = Path(self.temp_dir.name) / "packages"
        try:
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("research-skill/SKILL.md", """---\nid: research_skill\nname: research-skill\ndescription: Research a topic with supplied references.\n---\n\n# Research\nUse the reference material before answering.""")
                archive.writestr("research-skill/references/guide.md", "Reference text")
                archive.writestr("research-skill/scripts/collect.py", "raise RuntimeError('must not run')")
            result = self.request_json("/api/skills", {"bundle_base64": base64.b64encode(bundle.getvalue()).decode()}, self.token)
            self.assertEqual(result["skill"]["id"], "research_skill")
            stored = app.SKILL_PACKAGE_DIR / result["skill"]["id"] / "1.0.0"
            self.assertTrue((stored / "scripts" / "collect.py").exists())
            self.assertEqual((stored / "references" / "guide.md").read_text(), "Reference text")
        finally:
            app.SKILLS_DIR = original_skills_dir
            app.SKILL_PACKAGE_DIR = original_package_dir
            app.SKILLS = original_skills

    def test_context_budget_creates_linked_continuation_thread(self):
        initial = self.chat({"thread_id": "", "content": "这是第一轮需要被交接的内容"})
        original_thread_id = next(event["data"]["thread_id"] for event in initial if event["event"] == "meta")
        original_budget = app.MAX_CONTEXT_TOKENS
        app.MAX_CONTEXT_TOKENS = 1
        try:
            continued = self.chat({"thread_id": original_thread_id, "content": "这是自动续聊后的新问题"})
        finally:
            app.MAX_CONTEXT_TOKENS = original_budget
        continuation_id = next(event["data"]["thread_id"] for event in continued if event["event"] == "meta")
        self.assertNotEqual(continuation_id, original_thread_id)
        detail = self.request_json(f"/api/threads/{continuation_id}", token=self.token)["thread"]
        self.assertEqual(detail["parent_thread_id"], original_thread_id)
        self.assertIn("用户目标", detail["handoff_summary"])

    def test_production_bootstrap_requires_explicit_admin_credentials(self):
        with patch.dict(
            app.os.environ,
            {"AGENT_PLATFORM_ENV": "production", "ADMIN_EMAIL": "", "ADMIN_PASSWORD": ""},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "ADMIN_EMAIL 和 ADMIN_PASSWORD"):
                app.bootstrap_admin_credentials()

        with patch.dict(
            app.os.environ,
            {
                "AGENT_PLATFORM_ENV": "production",
                "ADMIN_EMAIL": "OWNER@EXAMPLE.COM ",
                "ADMIN_PASSWORD": "a-strong-password",
                "ADMIN_NAME": "平台管理员",
            },
            clear=False,
        ):
            self.assertEqual(
                app.bootstrap_admin_credentials(),
                ("owner@example.com", "a-strong-password", "平台管理员"),
            )

    def test_multiple_turns_complete_and_history_is_stable(self):
        apps = self.request_json("/api/apps", token=self.token)["apps"]
        self.assertIn("local_artifacts", [app_item["id"] for app_item in apps])
        skills = self.request_json("/api/skills", token=self.token)["skills"]
        self.assertTrue(next(skill for skill in skills if skill["id"] == "file_artifact")["enabled"])

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
            [event["sequence"] for event in run_detail["events"]],
            list(range(1, len(run_detail["events"]) + 1)),
        )
        self.assertTrue(all(event["schema_version"] == 1 for event in run_detail["events"]))
        self.assertEqual(
            [event["type"] for event in run_detail["events"]],
            ["started", "execution_context", "skill_routed", "knowledge_not_needed", "plan_created", "model_request", "completed"],
        )
        self.assertIn("general_assistant", [skill["id"] for skill in json.loads(run_detail["run"]["skill_snapshot"])])
        self.assertIn("file_artifact", [skill["id"] for skill in json.loads(run_detail["run"]["skill_snapshot"])])
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

    def test_markdown_artifact_waits_for_confirmation_and_is_audited(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            events = self.chat({"thread_id": "", "content": "请生成 Markdown 文件，整理本次平台说明"})
            self.assertEqual(events[-1]["event"], "confirmation")
            meta = next(event["data"] for event in events if event["event"] == "meta")
            run_id = meta["run_id"]
            detail = self.request_json(f"/api/runs/{run_id}", token=self.token)
            self.assertEqual(detail["run"]["status"], "awaiting_confirmation")
            self.assertTrue(detail["steps"][0]["requires_confirmation"])
            self.assertEqual(detail["steps"][0]["status"], "awaiting_confirmation")

            result = self.request_json(f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token, timeout=30)
            self.assertTrue(result["approved"])
            self.assertEqual(result["artifact"]["kind"], "markdown")
            artifacts = self.request_json("/api/artifacts", token=self.token)["artifacts"]
            self.assertEqual(artifacts[0]["id"], result["artifact"]["id"])
            self.assertTrue(Path(artifacts[0]["storage_path"]).is_file())
            detail = self.request_json(f"/api/runs/{run_id}", token=self.token)
            thread_context = self.request_json(f"/api/threads/{detail['run']['thread_id']}/context", token=self.token)
            self.assertEqual(thread_context["outputs"][0]["id"], result["artifact"]["id"])
            self.assertNotIn("storage_path", thread_context["outputs"][0])
            self.assertEqual(detail["run"]["status"], "completed")
            self.assertIn("artifact_created", [event["type"] for event in detail["events"]])
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

    def test_file_capability_question_does_not_confirm_but_followup_generate_does(self):
        question_events = self.chat({"thread_id": "", "content": "你可以生成 md 文件吗？"})
        self.assertEqual(question_events[-1]["event"], "done")
        thread_id = next(event["data"]["thread_id"] for event in question_events if event["event"] == "meta")
        question_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        self.assertEqual(question_run["status"], "completed")

        generate_events = self.chat({"thread_id": thread_id, "content": "生成"})
        self.assertEqual(generate_events[-1]["event"], "confirmation")
        self.assertEqual(generate_events[-1]["data"]["kind"], "markdown")

    def test_rejected_artifact_request_creates_no_file(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            events = self.chat({"thread_id": "", "content": "创建 md 文件，输出项目计划"})
            run_id = next(event["data"]["run_id"] for event in events if event["event"] == "meta")
            result = self.request_json(f"/api/runs/{run_id}/confirmation", {"approved": False}, self.token)
            self.assertFalse(result["approved"])
            self.assertFalse(app.ARTIFACT_DIR.exists())
            detail = self.request_json(f"/api/runs/{run_id}", token=self.token)
            self.assertEqual(detail["run"]["status"], "cancelled")
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

    def test_user_can_cancel_a_pending_run_without_creating_an_artifact(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            events = self.chat({"thread_id": "", "content": "请生成 Markdown 文件，整理本次平台说明"})
            run_id = next(event["data"]["run_id"] for event in events if event["event"] == "meta")

            result = self.request_json(f"/api/runs/{run_id}/cancel", {}, self.token)
            self.assertEqual(result["status"], "cancelled")
            detail = self.request_json(f"/api/runs/{run_id}", token=self.token)
            self.assertEqual(detail["run"]["status"], "cancelled")
            self.assertEqual(detail["confirmation"]["status"], "cancelled")
            self.assertTrue(all(step["status"] == "cancelled" for step in detail["steps"]))
            self.assertIn("cancelled", [event["type"] for event in detail["events"]])
            self.assertFalse(app.ARTIFACT_DIR.exists())

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request_json(f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token)
            self.assertEqual(ctx.exception.code, 409)
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

    def test_xlsx_artifact_uses_a_fixed_workbook(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            events = self.chat({"thread_id": "", "content": "请生成 xlsx 文件，输出项目计划"})
            run_id = next(event["data"]["run_id"] for event in events if event["event"] == "meta")
            result = self.request_json(f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token, timeout=30)
            artifact = result["artifact"]
            self.assertEqual(artifact["kind"], "xlsx")
            artifacts = self.request_json("/api/artifacts", token=self.token)["artifacts"]
            path = Path(artifacts[0]["storage_path"])
            self.assertTrue(path.is_file())
            self.assertFalse(path.with_name(path.name + ".inspect.ndjson").exists())
            downloaded, content_type = self.download_artifact(artifact["id"])
            self.assertEqual(content_type, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.assertTrue(downloaded.startswith(b"PK"))
            with zipfile.ZipFile(path) as workbook:
                self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

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
        tool_call = next(json.loads(event["payload"]) for event in detail["events"] if event["type"] == "tool_call")
        tool_result = next(json.loads(event["payload"]) for event in detail["events"] if event["type"] == "tool_result")
        self.assertTrue(tool_call["tool_call_id"])
        self.assertEqual(tool_call["tool_call_id"], tool_result["tool_call_id"])

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

    def test_thread_folders_group_and_preserve_threads_on_delete(self):
        folder = self.request_json("/api/folders", {"name": "改动范围"}, self.token)["folder"]
        thread = self.request_json(
            "/api/threads", {"title": "接口改造", "folder_id": folder["id"]}, self.token
        )["thread"]
        self.assertEqual(thread["folder_id"], folder["id"])
        self.assertEqual(self.request_json("/api/folders", token=self.token)["folders"][0]["name"], "改动范围")

        moved = self.request_json(
            f"/api/threads/{thread['id']}", {"folder_id": ""}, self.token, method="PATCH"
        )["thread"]
        self.assertEqual(moved["folder_id"], "")

        self.request_json(
            f"/api/threads/{thread['id']}", {"folder_id": folder["id"]}, self.token, method="PATCH"
        )
        self.request_json(f"/api/folders/{folder['id']}", token=self.token, method="DELETE")
        retained = self.request_json(f"/api/threads/{thread['id']}", token=self.token)["thread"]
        self.assertEqual(retained["folder_id"], "")

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
        self.assertIn("参考资料：product.md（片段 1）", answer)
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        context = json.loads(run["execution_context"])
        self.assertEqual(context["knowledge_refs"][0]["filename"], "product.md")
        self.assertEqual(context["knowledge_route"], "retrieved")
        self.assertEqual(context["knowledge_match_count"], 1)
        self.assertIn("knowledge_retrieved", [event["type"] for event in self.request_json(f"/api/runs/{run['id']}", token=self.token)["events"]])
        thread_context = self.request_json(f"/api/threads/{thread_id}/context", token=self.token)
        self.assertEqual(thread_context["sources"][0]["filename"], "product.md")
        self.assertEqual(thread_context["sources"][0]["position"], 0)

        generic_events = self.chat({"thread_id": thread_id, "content": "请分析一下这个平台的界面布局"})
        generic_answer = "".join(event["data"].get("content", "") for event in generic_events)
        generic_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        generic_context = json.loads(generic_run["execution_context"])
        self.assertNotIn("参考资料：", generic_answer)
        self.assertEqual(generic_context["knowledge_route"], "not_needed")
        self.assertEqual(generic_context["knowledge_intent"]["reason"], "not_recognized")

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

    def test_startup_reconciles_interrupted_runs_but_preserves_confirmations(self):
        with app.db() as conn:
            conn.execute(
                "INSERT INTO threads (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("thread_recovery", "user_test", "恢复测试", app.now(), app.now()),
            )
            conn.execute(
                "INSERT INTO runs (id, thread_id, status, model, started_at) VALUES (?, ?, ?, ?, ?)",
                ("run_interrupted", "thread_recovery", "running", "test", app.now()),
            )
            conn.execute(
                "INSERT INTO runs (id, thread_id, status, model, started_at) VALUES (?, ?, ?, ?, ?)",
                ("run_waiting", "thread_recovery", "awaiting_confirmation", "test", app.now()),
            )

        app.init_db()

        with app.db() as conn:
            interrupted = conn.execute("SELECT status, error FROM runs WHERE id = 'run_interrupted'").fetchone()
            waiting = conn.execute("SELECT status FROM runs WHERE id = 'run_waiting'").fetchone()
            recovery_event = conn.execute(
                "SELECT type, sequence FROM run_events WHERE run_id = 'run_interrupted'"
            ).fetchone()
        self.assertEqual(interrupted["status"], "failed")
        self.assertIn("请重试", interrupted["error"])
        self.assertEqual(waiting["status"], "awaiting_confirmation")
        self.assertEqual(recovery_event["type"], "run_recovered")
        self.assertEqual(recovery_event["sequence"], 1)

    def test_delete_artifact_removes_file_and_record(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            events = self.chat({"thread_id": "", "content": "请生成 Markdown 文件，整理本次平台说明"})
            run_id = next(event["data"]["run_id"] for event in events if event["event"] == "meta")
            result = self.request_json(
                f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token, timeout=30
            )
            artifact_id = result["artifact"]["id"]
            artifacts = self.request_json("/api/artifacts", token=self.token)["artifacts"]
            self.assertEqual(len(artifacts), 1)

            delete_result = self.request_json(
                f"/api/artifacts/{artifact_id}", token=self.token, method="DELETE"
            )
            self.assertTrue(delete_result.get("ok"))

            artifacts_after = self.request_json("/api/artifacts", token=self.token)["artifacts"]
            self.assertEqual(len(artifacts_after), 0)

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request_json(f"/api/artifacts/{artifact_id}", token=self.token, method="DELETE")
            self.assertEqual(ctx.exception.code, 404)
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

    def test_get_run_includes_linked_artifact(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            events = self.chat({"thread_id": "", "content": "请生成 Markdown 文件，整理本次平台说明"})
            run_id = next(event["data"]["run_id"] for event in events if event["event"] == "meta")
            self.request_json(
                f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token, timeout=30
            )
            detail = self.request_json(f"/api/runs/{run_id}", token=self.token)
            self.assertIsNotNone(detail["artifact"])
            self.assertEqual(detail["artifact"]["kind"], "markdown")
            self.assertTrue(detail["artifact"]["filename"].endswith(".md"))
        finally:
            app.ARTIFACT_DIR = original_artifact_dir


if __name__ == "__main__":
    unittest.main()
