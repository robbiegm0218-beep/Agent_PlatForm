import json
import base64
import io
import subprocess
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
from server.account_deletion import delete_due_accounts
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
        self.assertIn("agent_intelligence", health)
        self.assertIn("enabled", health["agent_intelligence"])

    def test_api_security_headers_and_cross_origin_write_are_rejected(self):
        request = urllib.request.Request(f"{self.base_url}/api/health")
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertIn("form-action 'self'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")
        trace_request = urllib.request.Request(f"{self.base_url}/api/health", headers={"X-Request-ID": "trace_12345"})
        with urllib.request.urlopen(trace_request, timeout=3) as response:
            self.assertEqual(response.headers["X-Request-ID"], "trace_12345")
        cross_origin = urllib.request.Request(
            f"{self.base_url}/api/login", data=b'{}', method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        )
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(cross_origin, timeout=3)
        self.assertEqual(denied.exception.code, 403)

    def test_sensitive_values_are_redacted_before_logging(self):
        message = app.redact_sensitive_text("Authorization: Bearer abc123 password=hunter2 api_key: value")
        self.assertNotIn("abc123", message)
        self.assertNotIn("hunter2", message)
        self.assertNotIn("value", message)
        self.assertEqual(message.count("[REDACTED]"), 3)

    def test_agent_rollout_is_current_user_scoped(self):
        report = self.request_json("/api/agent-rollout", token=self.token)
        self.assertEqual(report["scope"], "current_user")
        self.assertIn(report["recommendation"], {"shadow", "rollback", "administrator_canary"})
        self.assertIn("v2_shadow_runs", report["shadow"])

    def test_shadow_run_is_recorded_and_counted_by_rollout_report(self):
        original = (app.AGENT_INTELLIGENCE_V2, app.AGENT_PLANNER_MODE, app.AGENT_EVIDENCE_MODE, app.AGENT_ORCHESTRATOR_MODE, app.AGENT_VERIFIER_MODE)
        try:
            app.AGENT_INTELLIGENCE_V2 = True
            app.AGENT_PLANNER_MODE = "shadow"
            app.AGENT_EVIDENCE_MODE = "shadow"
            app.AGENT_ORCHESTRATOR_MODE = "shadow"
            app.AGENT_VERIFIER_MODE = "shadow"
            events = self.chat({"thread_id": "", "content": "请制定一份产品调研方案"})
            self.assertEqual(events[-1]["event"], "done")
            thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
            run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
            context = json.loads(run["execution_context"])
            self.assertIn("task_frame", context)
            report = self.request_json("/api/agent-rollout", token=self.token)
            self.assertEqual(report["shadow"]["v2_shadow_runs"], 1)
            self.assertEqual(report["recommendation"], "shadow")
        finally:
            (app.AGENT_INTELLIGENCE_V2, app.AGENT_PLANNER_MODE, app.AGENT_EVIDENCE_MODE, app.AGENT_ORCHESTRATOR_MODE, app.AGENT_VERIFIER_MODE) = original

    def test_auth_service_login_logout_and_logout_all_sessions(self):
        second = self.request_json("/api/login", {"email": "admin@example.com", "password": "admin123"})["token"]
        self.request_json("/api/logout-all", {}, self.token)
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request_json("/api/me", token=second)
        self.assertEqual(failure.exception.code, 401)
        fresh = self.request_json("/api/login", {"email": "admin@example.com", "password": "admin123"})["token"]
        self.request_json("/api/logout", {}, fresh)
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request_json("/api/me", token=fresh)
        self.assertEqual(failure.exception.code, 401)

    def test_personal_account_password_change_revokes_sessions_and_audits(self):
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.request_json(
                "/api/password/change",
                {"current_password": "wrong", "new_password": "new-password-123"},
                self.token,
            )
        self.assertEqual(invalid.exception.code, 400)

        result = self.request_json(
            "/api/password/change",
            {"current_password": "admin123", "new_password": "new-password-123"},
            self.token,
        )
        self.assertTrue(result["requires_login"])
        with self.assertRaises(urllib.error.HTTPError) as expired:
            self.request_json("/api/me", token=self.token)
        self.assertEqual(expired.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError):
            self.request_json("/api/login", {"email": "admin@example.com", "password": "admin123"})
        fresh = self.request_json("/api/login", {"email": "admin@example.com", "password": "new-password-123"})
        events = self.request_json("/api/security-events", token=fresh["token"])["events"]
        self.assertTrue(any(item["event_type"] == "password_change" and item["outcome"] == "succeeded" for item in events))

    def test_local_password_reset_is_single_use_and_never_stored_raw(self):
        token = app.AUTH_SERVICE.create_password_reset("admin@example.com", ttl_seconds=60)
        self.assertTrue(token)
        with app.db() as conn:
            stored = conn.execute("SELECT token_hash FROM password_reset_tokens").fetchone()["token_hash"]
        self.assertNotEqual(stored, token)

        self.request_json(
            "/api/password-reset/confirm",
            {"token": token, "new_password": "reset-password-123"},
        )
        with self.assertRaises(urllib.error.HTTPError) as reused:
            self.request_json(
                "/api/password-reset/confirm",
                {"token": token, "new_password": "another-password-123"},
            )
        self.assertEqual(reused.exception.code, 400)
        fresh = self.request_json("/api/login", {"email": "admin@example.com", "password": "reset-password-123"})
        self.assertTrue(fresh["token"])

    def test_startup_status_and_schema_version_are_visible_after_login(self):
        status = self.request_json("/api/startup-status", token=self.token)
        self.assertTrue(status["required_ready"])
        self.assertTrue(status["schema"]["ready"])
        self.assertIn("app_version", status)
        health = self.request_json("/api/health")
        self.assertTrue(health["schema"]["ready"])
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], app.migration_status(conn)["latest_version"])

    def test_personal_data_export_requires_confirmation_and_excludes_credentials(self):
        thread = self.request_json("/api/threads", {"title": "导出测试"}, self.token)["thread"]
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages (id, thread_id, run_id, role, content, created_at) VALUES (?, ?, '', 'user', ?, ?)",
                ("export_message", thread["id"], "需要保留的对话内容", app.now()),
            )
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request_json("/api/data-export", {}, self.token)
        self.assertEqual(denied.exception.code, 409)
        with patch.object(app, "ARTIFACT_DIR", Path(self.temp_dir.name) / "artifacts"):
            result = self.request_json("/api/data-export", {"confirmation": "EXPORT_MY_DATA"}, self.token)
            artifact_id = result["artifact"]["id"]
            content, content_type = self.download_artifact(artifact_id)
        exported = json.loads(content.decode("utf-8"))
        self.assertEqual(content_type, "application/json")
        self.assertEqual(exported["format"], "agent-platform-personal-data-export/v1")
        self.assertIn("需要保留的对话内容", [item["content"] for item in exported["messages"]])
        self.assertIn("password_hash", exported["exclusions"])
        events = self.request_json("/api/security-events", token=self.token)["events"]
        self.assertTrue(any(item["event_type"] == "personal_data_export" for item in events))

    def test_personal_usage_is_current_user_scoped_and_returns_estimates(self):
        usage = self.request_json("/api/personal-usage", token=self.token)
        self.assertIn("day", usage)
        self.assertIn("month", usage)
        self.assertIn("storage", usage)
        self.assertEqual(usage["limits"]["daily_tokens"], app.PERSONAL_DAILY_TOKEN_LIMIT)
        self.assertEqual(usage["day"]["runs"], 0)
        self.assertIn("Token", usage["token_note"])

    def test_daily_run_budget_blocks_new_chat_but_keeps_history_available(self):
        original_limit = app.PERSONAL_DAILY_RUN_LIMIT
        app.PERSONAL_DAILY_RUN_LIMIT = 1
        try:
            thread = self.request_json("/api/threads", {"title": "预算历史"}, self.token)["thread"]
            with app.db() as conn:
                conn.execute(
                    "INSERT INTO runs (id, thread_id, status, model, started_at, completed_at) VALUES (?, ?, 'completed', ?, ?, ?)",
                    ("budget_run", thread["id"], app.DEEPSEEK_MODEL, app.now(), app.now()),
                )
            with self.assertRaises(urllib.error.HTTPError) as limited:
                self.request_json("/api/chat", {"thread_id": "", "content": "新的任务"}, self.token)
            self.assertEqual(limited.exception.code, 429)
            self.assertTrue(self.request_json("/api/threads", token=self.token)["threads"])
        finally:
            app.PERSONAL_DAILY_RUN_LIMIT = original_limit

    def test_single_run_token_budget_blocks_oversized_new_chat(self):
        original_limit = app.PERSONAL_SINGLE_RUN_TOKEN_LIMIT
        app.PERSONAL_SINGLE_RUN_TOKEN_LIMIT = 1
        try:
            with self.assertRaises(urllib.error.HTTPError) as limited:
                self.request_json("/api/chat", {"thread_id": "", "content": "新的任务"}, self.token)
            self.assertEqual(limited.exception.code, 429)
        finally:
            app.PERSONAL_SINGLE_RUN_TOKEN_LIMIT = original_limit

    def test_login_failures_lock_the_source_without_storing_passwords(self):
        original_limit = app.AUTH_SERVICE.login_failure_limit
        app.AUTH_SERVICE.login_failure_limit = 1
        try:
            with self.assertRaises(urllib.error.HTTPError) as failed:
                self.request_json("/api/login", {"email": "admin@example.com", "password": "wrong-password"})
            self.assertEqual(failed.exception.code, 429)
            with self.assertRaises(urllib.error.HTTPError) as locked:
                self.request_json("/api/login", {"email": "admin@example.com", "password": "admin123"})
            self.assertEqual(locked.exception.code, 429)
            with app.db() as conn:
                throttle = conn.execute("SELECT scope_key, failure_count FROM login_throttles").fetchone()
            self.assertTrue(throttle["scope_key"].startswith(("email:", "source:")))
            self.assertEqual(throttle["failure_count"], 1)
        finally:
            app.AUTH_SERVICE.login_failure_limit = original_limit

    def test_manual_tools_respect_run_budget_before_execution(self):
        original_limit = app.PERSONAL_DAILY_RUN_LIMIT
        app.PERSONAL_DAILY_RUN_LIMIT = 1
        try:
            thread = self.request_json("/api/threads", {"title": "工具预算"}, self.token)["thread"]
            with app.db() as conn:
                conn.execute("INSERT INTO runs (id, thread_id, status, model, started_at, completed_at) VALUES (?, ?, 'completed', ?, ?, ?)", ("manual_tool_budget_run", thread["id"], app.DEEPSEEK_MODEL, app.now(), app.now()))
            with self.assertRaises(urllib.error.HTTPError) as limited:
                self.request_json("/api/tools/platform_status/execute", {"arguments": {}}, self.token)
            self.assertEqual(limited.exception.code, 429)
        finally:
            app.PERSONAL_DAILY_RUN_LIMIT = original_limit

    def test_account_deletion_request_requires_confirmation_and_can_be_cancelled(self):
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request_json("/api/account-deletion/request", {}, self.token)
        self.assertEqual(denied.exception.code, 409)
        scheduled = self.request_json("/api/account-deletion/request", {"confirmation": "DELETE_MY_ACCOUNT"}, self.token)
        self.assertGreater(scheduled["scheduled_for"], app.now())
        status = self.request_json("/api/account-deletion", token=self.token)["request"]
        self.assertEqual(status["status"], "scheduled")
        self.assertTrue(self.request_json("/api/account-deletion/cancel", {}, self.token)["ok"])

    def test_due_account_deletion_is_dry_run_first_then_removes_personal_data(self):
        data_dir = Path(self.temp_dir.name) / "deletion-data"
        knowledge_file = data_dir / "knowledge" / "admin" / "source.md"
        artifact_file = data_dir / "artifacts" / "admin" / "answer.md"
        knowledge_file.parent.mkdir(parents=True)
        artifact_file.parent.mkdir(parents=True)
        knowledge_file.write_text("private knowledge", encoding="utf-8")
        artifact_file.write_text("private artifact", encoding="utf-8")
        with app.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE email = 'admin@example.com'").fetchone()["id"]
            conn.execute("INSERT INTO threads (id, user_id, title, created_at, updated_at) VALUES ('delete_thread', ?, '删除', ?, ?)", (user_id, app.now(), app.now()))
            conn.execute("INSERT INTO runs (id, thread_id, status, model, started_at) VALUES ('delete_run', 'delete_thread', 'completed', ?, ?)", (app.DEEPSEEK_MODEL, app.now()))
            conn.execute("INSERT INTO knowledge_documents (id, user_id, filename, storage_path, mime_type, content_hash, size_bytes, chunk_count, created_at, created_by_user_id) VALUES ('delete_doc', ?, 'source.md', ?, 'text/markdown', 'hash', 1, 1, ?, ?)", (user_id, str(knowledge_file), app.now(), user_id))
            conn.execute("INSERT INTO artifacts (id, user_id, run_id, filename, kind, storage_path, created_at) VALUES ('delete_artifact', ?, 'delete_run', 'answer.md', 'markdown', ?, ?)", (user_id, str(artifact_file), app.now()))
            conn.execute("INSERT INTO account_deletion_requests (user_id, status, requested_at, scheduled_for, cancelled_at) VALUES (?, 'scheduled', 0, 0, 0)", (user_id,))
        preview = delete_due_accounts(app.DB_PATH, data_dir, execute=False, current_ns=1)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["planned"][0]["user_id"], user_id)
        with app.db() as conn:
            self.assertIsNotNone(conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())
        result = delete_due_accounts(app.DB_PATH, data_dir, execute=True, current_ns=1)
        self.assertFalse(result["dry_run"])
        self.assertFalse(knowledge_file.exists())
        self.assertFalse(artifact_file.exists())
        with app.db() as conn:
            self.assertIsNone(conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())

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

    def test_completed_run_keeps_reasoning_summary_for_later_viewing(self):
        events = self.chat({"thread_id": "", "content": "请说明平台能力"})
        meta = next(event["data"] for event in events if event["event"] == "meta")

        detail = self.request_json(f"/api/runs/{meta['run_id']}", token=self.token)
        summary = next(event for event in detail["events"] if event["type"] == "reasoning_summary")
        self.assertTrue(json.loads(summary["payload"])["items"])

    def test_thread_context_deduplicates_knowledge_sources_by_document(self):
        events = self.chat({"thread_id": "", "content": "你好"})
        meta = next(event["data"] for event in events if event["event"] == "meta")
        with app.db() as conn:
            context = json.loads(conn.execute("SELECT execution_context FROM runs WHERE id = ?", (meta["run_id"],)).fetchone()["execution_context"])
            context["knowledge_refs"] = [
                {"document_id": "doc_1", "filename": "同一份资料.md", "position": 0, "excerpt": "第一处命中"},
                {"document_id": "doc_1", "filename": "同一份资料.md", "position": 1, "excerpt": "第二处命中"},
                {"document_id": "doc_2", "filename": "另一份资料.md", "position": 0, "excerpt": "第三处命中"},
            ]
            conn.execute("UPDATE runs SET execution_context = ? WHERE id = ?", (json.dumps(context, ensure_ascii=False), meta["run_id"]))

        thread_context = self.request_json(f"/api/threads/{meta['thread_id']}/context", token=self.token)
        sources = [item for item in thread_context["sources"] if item["kind"] == "knowledge"]
        # The fabricated document IDs are deliberately not visible to this test
        # user.  The API must still deduplicate them without leaking metadata.
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(item.get("redacted") for item in sources))
        self.assertEqual([item["title"] for item in sources], ["资料引用已隐藏", "资料引用已隐藏"])

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
        self.assertIn("目标", detail["handoff_summary"])
        continuation_context = self.request_json(
            f"/api/threads/{continuation_id}/context", token=self.token
        )["structured_context"]
        self.assertTrue(any("第一轮" in item["text"] for item in continuation_context["goals"]))

    def test_structured_context_tracks_sources_and_user_corrections(self):
        first = self.chat({
            "thread_id": "",
            "content": "为星河项目制定发布计划。项目名：星河。必须使用中文。",
        })
        thread_id = next(event["data"]["thread_id"] for event in first if event["event"] == "meta")
        self.chat({"thread_id": thread_id, "content": "目标改为制定迁移计划，最终采用分批迁移。"})

        detail = self.request_json(f"/api/threads/{thread_id}", token=self.token)
        user_message_ids = {message["id"] for message in detail["messages"] if message["role"] == "user"}
        context = self.request_json(f"/api/threads/{thread_id}/context", token=self.token)["structured_context"]
        active_goals = [item for item in context["goals"] if item["status"] == "active"]
        self.assertEqual([item["text"] for item in active_goals], ["制定迁移计划，最终采用分批迁移。"])
        self.assertIn(active_goals[0]["source_message_id"], user_message_ids)
        self.assertTrue(any("星河" in item["text"] for item in context["entities"]))

        latest_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        frozen = json.loads(latest_run["execution_context"])["structured_context"]
        self.assertEqual(frozen["goals"][0]["source_message_id"], active_goals[0]["source_message_id"])

    def test_explicit_memory_lifecycle_injection_and_usage_audit(self):
        first = self.chat({"thread_id": "", "content": "我的偏好是使用简洁中文。"})
        thread_id = next(event["data"]["thread_id"] for event in first if event["event"] == "meta")
        detail = self.request_json(f"/api/threads/{thread_id}", token=self.token)
        source_id = next(message["id"] for message in detail["messages"] if message["role"] == "user")

        candidates = self.request_json(
            "/api/memories/candidates",
            {"content": "我的偏好是使用简洁中文。", "source_message_id": source_id},
            self.token,
        )["candidates"]
        self.assertEqual(candidates[0]["kind"], "preference")
        self.assertEqual(self.request_json("/api/memories", token=self.token)["memories"], [])
        with self.assertRaises(urllib.error.HTTPError) as missing_confirmation:
            self.request_json("/api/memories", {**candidates[0], "scope_type": "global"}, self.token)
        self.assertEqual(missing_confirmation.exception.code, 400)

        created = self.request_json(
            "/api/memories",
            {**candidates[0], "scope_type": "global", "confirmed": True},
            self.token,
        )["memory"]
        memory_id = created["id"]
        used = self.chat({"thread_id": "", "content": "请用中文回答这个问题。"})
        used_thread_id = next(event["data"]["thread_id"] for event in used if event["event"] == "meta")
        used_run = self.request_json(f"/api/threads/{used_thread_id}/runs", token=self.token)["runs"][0]
        self.assertEqual(json.loads(used_run["execution_context"])["memories"][0]["id"], memory_id)
        listed = self.request_json("/api/memories", token=self.token)["memories"]
        self.assertEqual(listed[0]["use_count"], 1)

        self.request_json(f"/api/memories/{memory_id}", {"status": "disabled"}, self.token, method="PATCH")
        disabled = self.chat({"thread_id": "", "content": "请继续用中文回答。"})
        disabled_thread_id = next(event["data"]["thread_id"] for event in disabled if event["event"] == "meta")
        disabled_run = self.request_json(f"/api/threads/{disabled_thread_id}/runs", token=self.token)["runs"][0]
        self.assertEqual(json.loads(disabled_run["execution_context"])["memories"], [])

        self.request_json(f"/api/memories/{memory_id}", token=self.token, method="DELETE")
        self.assertEqual(self.request_json("/api/memories", token=self.token)["memories"], [])
        with self.assertRaises(urllib.error.HTTPError) as sensitive:
            self.request_json(
                "/api/memories",
                {"kind": "project_fact", "content": "API_KEY: secret-value", "scope_type": "global", "confirmed": True},
                self.token,
            )
        self.assertEqual(sensitive.exception.code, 400)

    def test_memory_isolation_and_expiration(self):
        with app.db() as conn:
            timestamp = app.now()
            current_user_id = conn.execute("SELECT id FROM users WHERE email = ?", ("admin@example.com",)).fetchone()["id"]
            conn.execute(
                """INSERT INTO memories
                   (id, user_id, kind, content, scope_type, scope_id, confidence, status, expires_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'global', '', 'confirmed', 'active', 0, ?, ?)""",
                ("other_memory", "other_user", "preference", "使用中文回答", timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO memories
                   (id, user_id, kind, content, scope_type, scope_id, confidence, status, expires_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'global', '', 'confirmed', 'active', ?, ?, ?)""",
                ("expired_memory", current_user_id, "preference", "使用中文回答", timestamp - 1, timestamp, timestamp),
            )
        self.assertEqual(self.request_json("/api/memories", token=self.token)["memories"][0]["effective_status"], "expired")
        events = self.chat({"thread_id": "", "content": "请使用中文回答。"})
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        self.assertEqual(json.loads(run["execution_context"])["memories"], [])

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
        event_types = [event["type"] for event in run_detail["events"]]
        non_phase_events = [event_type for event_type in event_types if event_type != "phase_changed"]
        self.assertEqual(non_phase_events[:4], ["started", "execution_context", "skill_routed", "reasoning_summary"])
        self.assertIn("task_frame_planned", non_phase_events)
        self.assertIn("orchestrator_transition", non_phase_events)
        self.assertIn("knowledge_not_needed", non_phase_events)
        self.assertIn("plan_created", non_phase_events)
        self.assertIn("model_request", non_phase_events)
        self.assertIn("task_verified", non_phase_events)
        self.assertEqual(non_phase_events[-1], "completed")
        self.assertEqual(
            [json.loads(event["payload"])["to"] for event in run_detail["events"] if event["type"] == "phase_changed"],
            ["generating", "completed"],
        )
        self.assertIn("general_assistant", [skill["id"] for skill in json.loads(run_detail["run"]["skill_snapshot"])])
        self.assertIn("file_artifact", [skill["id"] for skill in json.loads(run_detail["run"]["skill_snapshot"])])
        context = json.loads(run_detail["run"]["execution_context"])
        self.assertEqual(context["model"], app.DEEPSEEK_MODEL)
        self.assertEqual(context["allowed_tool_ids"], [])
        self.assertEqual(context["decision_policy"]["version"], "decision-quality-v1")
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
            self.assertEqual(detail["run"]["run_phase"], "awaiting_confirmation")
            self.assertTrue(detail["steps"][0]["requires_confirmation"])
            self.assertEqual(detail["steps"][0]["status"], "awaiting_confirmation")
            self.assertTrue(detail["steps"][0]["idempotency_key"])
            self.assertEqual(detail["steps"][0]["resume_policy"], "resume_from_contract")
            self.assertIn("task_preview", json.loads(detail["steps"][0]["input_json"]))
            self.assertEqual(detail["confirmation"]["risk_level"], "local_write")
            self.assertEqual(detail["confirmation"]["tool_id"], "create_artifact")
            self.assertEqual(len(detail["confirmations"]), 1)
            self.assertEqual(detail["confirmations"][0]["position"], 1)
            self.assertIn("删除该文件", detail["confirmation"]["rollback_summary"])
            self.assertEqual(detail["confirmation"]["idempotency_key"], f"artifact:{run_id}:markdown")

            result = self.request_json(f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token, timeout=30)
            self.assertTrue(result["approved"])
            resumed = self.request_json(f"/api/runs/{run_id}", token=self.token)
            self.assertEqual(resumed["run"]["run_phase"], "completed")
            self.assertTrue(any(event["type"] == "phase_changed" for event in resumed["events"]))
            self.assertEqual(json.loads(resumed["steps"][0]["output_json"])["status"], "completed")
            self.assertEqual(result["artifact"]["kind"], "markdown")
            artifacts = self.request_json("/api/artifacts", token=self.token)["artifacts"]
            self.assertEqual(artifacts[0]["id"], result["artifact"]["id"])
            self.assertNotIn("storage_path", artifacts[0])
            with app.db() as conn:
                stored = conn.execute("SELECT storage_path FROM artifacts WHERE id = ?", (artifacts[0]["id"],)).fetchone()
            self.assertTrue(Path(stored["storage_path"]).is_file())
            detail = self.request_json(f"/api/runs/{run_id}", token=self.token)
            thread_context = self.request_json(f"/api/threads/{detail['run']['thread_id']}/context", token=self.token)
            self.assertEqual(thread_context["outputs"][0]["id"], result["artifact"]["id"])
            self.assertNotIn("storage_path", thread_context["outputs"][0])
            self.assertEqual(detail["run"]["status"], "completed")
            self.assertIn("artifact_created", [event["type"] for event in detail["events"]])
            artifact_verification = [event for event in detail["events"] if event["type"] == "task_verified" and json.loads(event["payload"]).get("stage") == "artifact_created"]
            self.assertEqual(len(artifact_verification), 1)
            self.assertTrue(json.loads(artifact_verification[0]["payload"])["passed"])
            repeated = app.create_artifact(artifacts[0]["user_id"], run_id, "markdown", "ignored", "ignored")
            self.assertEqual(repeated["id"], result["artifact"]["id"])
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

    def test_artifact_command_can_use_the_previous_answer_as_file_content(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        try:
            thread = self.request_json("/api/threads", {"title": "上文生成文件"}, self.token)["thread"]
            with app.db() as conn:
                conn.execute("INSERT INTO messages (id, thread_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                    ("previous_answer", thread["id"], "这是需要完整写入文件的上一条回答。\n\n包含第二段。", app.now()))
            events = self.chat({"thread_id": thread["id"], "content": "把上面内容生成MD文件"})
            self.assertEqual(events[-1]["event"], "confirmation")
            run_id = next(event["data"]["run_id"] for event in events if event["event"] == "meta")
            result = self.request_json(f"/api/runs/{run_id}/confirmation", {"approved": True}, self.token, timeout=30)
            self.assertEqual(result["content"], "已根据上一次回答生成文件。")
            downloaded, content_type = self.download_artifact(result["artifact"]["id"])
            self.assertEqual(content_type, "text/markdown")
            self.assertIn("这是需要完整写入文件的上一条回答。", downloaded.decode("utf-8"))
            self.assertNotIn("把上面内容生成MD文件", downloaded.decode("utf-8"))
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
            self.assertNotIn("storage_path", artifacts[0])
            with app.db() as conn:
                stored = conn.execute("SELECT storage_path FROM artifacts WHERE id = ?", (artifact["id"],)).fetchone()
            path = Path(stored["storage_path"])
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
        events = self.chat({"thread_id": "", "content": "请分析当前平台状态，并给出优化方案"})
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
        tool_steps = [step for step in detail["steps"] if json.loads(step["input_json"]).get("phase") == "executing_tool"]
        self.assertEqual(len(tool_steps), 1)
        self.assertEqual(tool_steps[0]["status"], "completed")

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
        thread = self.request_json(f"/api/threads/{thread_id}", token=self.token)
        assistant_message = next(message for message in thread["messages"] if message["role"] == "assistant")
        self.assertEqual(assistant_message["run_id"], run["id"])
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
        self.assertIn("success_rate", metrics["tools"])
        self.assertIn("executor", metrics["model_roles"])
        self.assertGreaterEqual(metrics["model_roles"]["executor"]["calls"], 1)
        self.assertIn("confirmation_rejection_rate", metrics["tools"])
        self.assertGreaterEqual(metrics["tools"]["average_duration_ms"], 0)
        audit_runs = self.request_json("/api/runs?tier=quick", token=self.token)["runs"]
        self.assertEqual(len(audit_runs), 1)
        self.assertEqual(audit_runs[0]["task_tier"], "quick")

    def test_manual_read_only_tool_execution_is_audited_and_validated(self):
        result = self.request_json("/api/tools/platform_status/execute", {"arguments": {}}, self.token)
        self.assertEqual(result["invocation"]["status"], "completed")
        invocations = self.request_json("/api/tool-invocations", token=self.token)["invocations"]
        self.assertEqual(invocations[0]["tool_id"], "platform_status")
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request_json("/api/tools/search_workspace_files/execute", {"arguments": {}}, self.token)
        self.assertEqual(failure.exception.code, 400)

    def test_project_space_members_share_visibility_but_keep_thread_editing_private(self):
        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("member_user", "member@example.com", app.hash_password("member123"), "项目成员", app.now()))
        member_token = self.request_json("/api/login", {"email": "member@example.com", "password": "member123"})["token"]
        space = self.request_json("/api/folders", {"name": "共享项目", "section": "project"}, self.token)["folder"]
        invitation = self.request_json(f"/api/folders/{space['id']}/invitations", {"email": "member@example.com"}, self.token)["invitation"]
        self.assertEqual(invitation["status"], "accepted")
        member_thread = self.request_json("/api/threads", {"title": "成员任务", "folder_id": space["id"]}, member_token)["thread"]
        owner_threads = self.request_json("/api/threads", token=self.token)["threads"]
        self.assertEqual(next(item for item in owner_threads if item["id"] == member_thread["id"])["author_name"], "项目成员")
        space_detail = self.request_json(f"/api/folders/{space['id']}", token=member_token)
        self.assertEqual(space_detail["tasks"][0]["author_name"], "项目成员")
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request_json(f"/api/threads/{member_thread['id']}", {"title": "越权编辑"}, self.token, method="PATCH")
        self.assertEqual(failure.exception.code, 404)

    def test_space_invitation_auto_join_and_member_management_permissions(self):
        owner_id = self.request_json("/api/me", token=self.token)["user"]["id"]
        space = self.request_json("/api/folders", {"name": "成员协作", "section": "project"}, self.token)["folder"]
        invitation = self.request_json(
            f"/api/folders/{space['id']}/invitations", {"email": "pending-member@example.com"}, self.token
        )["invitation"]
        self.assertEqual(invitation["status"], "pending")
        with self.assertRaises(urllib.error.HTTPError) as duplicate:
            self.request_json(f"/api/folders/{space['id']}/invitations", {"email": "pending-member@example.com"}, self.token)
        self.assertEqual(duplicate.exception.code, 409)

        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("pending_member", "pending-member@example.com", app.hash_password("member123"), "待加入成员", app.now()))
        member_token = self.request_json("/api/login", {"email": "pending-member@example.com", "password": "member123"})["token"]
        detail = self.request_json(f"/api/folders/{space['id']}", token=member_token)
        self.assertIn("pending_member", [member["id"] for member in detail["members"]])
        self.assertEqual(detail["invitations"][0]["status"], "accepted")

        with self.assertRaises(urllib.error.HTTPError) as non_owner_invite:
            self.request_json(f"/api/folders/{space['id']}/invitations", {"email": "other@example.com"}, member_token)
        self.assertEqual(non_owner_invite.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as owner_removal:
            self.request_json(f"/api/folders/{space['id']}/members/{owner_id}", token=self.token, method="DELETE")
        self.assertEqual(owner_removal.exception.code, 409)
        self.assertTrue(self.request_json(f"/api/folders/{space['id']}/members/pending_member", token=self.token, method="DELETE")["ok"])
        detail = self.request_json(f"/api/folders/{space['id']}", token=self.token)
        self.assertNotIn("pending_member", [member["id"] for member in detail["members"]])

    def test_project_spaces_are_isolated_except_for_explicit_membership(self):
        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("isolated_user", "isolated@example.com", app.hash_password("member123"), "隔离用户", app.now()))
        member_token = self.request_json("/api/login", {"email": "isolated@example.com", "password": "member123"})["token"]
        owner_space = self.request_json("/api/folders", {"name": "所有者空间", "section": "project"}, self.token)["folder"]
        member_space = self.request_json("/api/folders", {"name": "成员私有空间", "section": "project"}, member_token)["folder"]

        self.request_json(f"/api/folders/{owner_space['id']}/invitations", {"email": "isolated@example.com"}, self.token)
        member_folders = self.request_json("/api/folders", token=member_token)["folders"]
        self.assertEqual({folder["id"] for folder in member_folders}, {owner_space["id"], member_space["id"]})
        self.assertEqual(self.request_json(f"/api/folders/{owner_space['id']}", token=member_token)["space"]["id"], owner_space["id"])
        with self.assertRaises(urllib.error.HTTPError) as foreign_space:
            self.request_json(f"/api/folders/{member_space['id']}", token=self.token)
        self.assertEqual(foreign_space.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as foreign_task:
            self.request_json("/api/threads", {"title": "跨空间任务", "folder_id": member_space["id"]}, self.token)
        self.assertEqual(foreign_task.exception.code, 400)

    def test_project_knowledge_is_shared_in_its_space_and_not_in_general_search(self):
        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("knowledge_member", "knowledge-member@example.com", app.hash_password("member123"), "资料成员", app.now()))
        member_token = self.request_json("/api/login", {"email": "knowledge-member@example.com", "password": "member123"})["token"]
        space = self.request_json("/api/folders", {"name": "资料项目", "section": "project"}, self.token)["folder"]
        self.request_json(f"/api/folders/{space['id']}/invitations", {"email": "knowledge-member@example.com"}, self.token)
        payload = {"filename": "项目资料.md", "mime_type": "text/markdown", "content_base64": base64.b64encode("项目专属指标是 42".encode("utf-8")).decode("ascii")}
        document = self.request_json(f"/api/folders/{space['id']}/knowledge", payload, self.token)["document"]
        self.assertEqual(document["scope"], "project")
        self.assertEqual(document["project_space_id"], space["id"])
        self.assertEqual(self.request_json(f"/api/knowledge/search?query={quote('项目专属指标')}", token=self.token)["results"], [])
        general = self.request_json("/api/knowledge", {
            "filename": "通用资料.md", "mime_type": "text/markdown",
            "content_base64": base64.b64encode("通用指标是 99".encode("utf-8")).decode("ascii"),
        }, self.token)["document"]
        member_space = self.request_json(f"/api/folders/{space['id']}", token=member_token)
        self.assertEqual(member_space["knowledge_documents"][0]["filename"], "项目资料.md")
        self.assertEqual(len(app.search_knowledge("knowledge_member", "项目专属指标", project_space_id=space["id"])), 1)
        matches = app.search_knowledge(self.request_json("/api/me", token=self.token)["user"]["id"], "通用指标", project_space_id=space["id"])
        self.assertEqual(matches[0]["document_id"], general["id"])
        self.request_json(f"/api/folders/{space['id']}", token=self.token, method="DELETE")
        self.assertEqual(app.search_knowledge("knowledge_member", "项目专属指标", project_space_id=space["id"]), [])

    def test_project_knowledge_delete_requires_space_owner(self):
        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("knowledge_delete_member", "knowledge-delete-member@example.com", app.hash_password("member123"), "资料成员", app.now()))
        member_token = self.request_json("/api/login", {"email": "knowledge-delete-member@example.com", "password": "member123"})["token"]
        space = self.request_json("/api/folders", {"name": "资料权限项目", "section": "project"}, self.token)["folder"]
        self.request_json(f"/api/folders/{space['id']}/invitations", {"email": "knowledge-delete-member@example.com"}, self.token)
        document = self.request_json(f"/api/folders/{space['id']}/knowledge", {
            "filename": "仅所有者可删.md", "mime_type": "text/markdown",
            "content_base64": base64.b64encode("受保护的项目资料".encode("utf-8")).decode("ascii"),
        }, self.token)["document"]
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request_json(f"/api/knowledge/{document['id']}", token=member_token, method="DELETE")
        self.assertEqual(denied.exception.code, 404)
        self.assertTrue(self.request_json(f"/api/knowledge/{document['id']}", token=self.token, method="DELETE")["ok"])

    def test_historical_knowledge_sources_are_redacted_when_viewer_loses_access(self):
        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("citation_member", "citation-member@example.com", app.hash_password("member123"), "引用成员", app.now()))
        member_token = self.request_json("/api/login", {"email": "citation-member@example.com", "password": "member123"})["token"]
        space = self.request_json("/api/folders", {"name": "历史引用项目", "section": "project"}, self.token)["folder"]
        self.request_json(f"/api/folders/{space['id']}/invitations", {"email": "citation-member@example.com"}, self.token)
        thread = self.request_json("/api/threads", {"title": "历史资料任务", "folder_id": space["id"]}, self.token)["thread"]
        with app.db() as conn:
            conn.execute("""INSERT INTO runs (id, thread_id, status, model, started_at, execution_context)
                VALUES (?, ?, 'completed', 'test', ?, ?)""", ("redacted_source_run", thread["id"], app.now(), json.dumps({"knowledge_refs": [{"document_id": "deleted_or_private_doc", "filename": "机密路线图.md", "position": 0, "excerpt": "不得向项目成员展示"}]})))
        context = self.request_json(f"/api/threads/{thread['id']}/context", token=member_token)
        self.assertEqual(context["sources"], [{"kind": "knowledge", "title": "资料引用已隐藏", "redacted": True, "run_id": "redacted_source_run", "used_at": context["sources"][0]["used_at"]}])
        detail = self.request_json(f"/api/folders/{space['id']}", token=member_token)
        self.assertEqual(detail["sources"][0]["title"], "资料引用已隐藏")
        self.assertTrue(detail["sources"][0]["redacted"])
        self.assertNotIn("机密路线图", json.dumps({"sources": detail["sources"]}, ensure_ascii=False))

    def test_execution_modes_are_frozen_and_constrain_knowledge_and_file_tools(self):
        off_events = self.chat({
            "thread_id": "", "content": "请根据本地资料说明产品指标", "knowledge_mode": "off", "file_mode": "off",
        })
        off_thread_id = next(event["data"]["thread_id"] for event in off_events if event["event"] == "meta")
        off_run = self.request_json(f"/api/threads/{off_thread_id}/runs", token=self.token)["runs"][0]
        off_context = json.loads(off_run["execution_context"])
        self.assertEqual(off_context["execution_modes"], {"knowledge": "off", "web": "auto", "file": "off", "source": "general"})
        self.assertEqual(off_context["knowledge_refs"], [])
        self.assertNotIn("search_workspace_files", off_context["allowed_tool_ids"])

        required_events = self.chat({
            "thread_id": "", "content": "简述平台能力", "source_mode": "local_only",
        })
        required_thread_id = next(event["data"]["thread_id"] for event in required_events if event["event"] == "meta")
        required_run = self.request_json(f"/api/threads/{required_thread_id}/runs", token=self.token)["runs"][0]
        required_context = json.loads(required_run["execution_context"])
        self.assertEqual(required_context["execution_modes"]["knowledge"], "required")
        self.assertEqual(required_context["execution_modes"]["web"], "off")
        self.assertIn(required_context["knowledge_route"], {"retrieved", "required_no_match"})

    def test_invalid_execution_mode_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.request_json("/api/chat", {"thread_id": "", "content": "测试", "web_mode": "always"}, self.token)
        self.assertEqual(invalid.exception.code, 400)

    def test_route_preview_matches_execution_mode_constraints_without_creating_a_run(self):
        preview = self.request_json(
            "/api/route-preview",
            {"content": "请根据本地资料说明产品指标", "source_mode": "local_only", "file_mode": "off"},
            self.token,
        )
        self.assertTrue(preview["ready"])
        self.assertEqual(preview["modes"]["knowledge"], "required")
        self.assertEqual(preview["modes"]["web"], "off")
        self.assertEqual(preview["modes"]["file"], "off")
        self.assertFalse(any(tool["id"] == "search_workspace_files" for tool in preview["allowed_tools"]))
        self.assertEqual(self.request_json("/api/threads", token=self.token)["threads"], [])

    def test_task_router_keeps_structured_short_tasks_out_of_quick_mode(self):
        self.assertEqual(app.infer_task_profile("请改写这段通知")["task_tier"], "standard")
        self.assertEqual(app.infer_task_profile("分析这段代码")["task_tier"], "standard")
        self.assertEqual(app.infer_task_profile("补充下一步待办")["task_tier"], "standard")

    def test_spaces_group_and_preserve_tasks_on_delete(self):
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

    def test_first_message_creates_a_thread_inside_requested_folder(self):
        folder = self.request_json("/api/folders", {"name": "产品项目", "section": "project"}, self.token)["folder"]
        events = self.chat({"thread_id": "", "folder_id": folder["id"], "content": "整理产品发布计划"})
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        thread = self.request_json(f"/api/threads/{thread_id}", token=self.token)["thread"]
        self.assertEqual(thread["folder_id"], folder["id"])
        self.assertEqual(thread["title"], "整理产品发布计划")

    def test_spaces_keep_independent_order_and_reject_task_folders(self):
        project_a = self.request_json(
            "/api/folders", {"name": "项目 A", "section": "project"}, self.token
        )["folder"]
        project_b = self.request_json(
            "/api/folders", {"name": "项目 B", "section": "project"}, self.token
        )["folder"]
        self.assertEqual(project_a["section"], "project")
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self.request_json("/api/folders", {"name": "日常任务", "section": "conversation"}, self.token)
        self.assertEqual(rejected.exception.code, 400)

        renamed = self.request_json(
            f"/api/folders/{project_a['id']}", {"name": "项目 A（重命名）"}, self.token, method="PATCH"
        )["folder"]
        self.assertEqual(renamed["name"], "项目 A（重命名）")

        self.request_json(
            f"/api/folders/{project_b['id']}", {"position": 0}, self.token, method="PATCH"
        )
        folders = self.request_json("/api/folders", token=self.token)["folders"]
        self.assertEqual([(folder["section"], folder["name"]) for folder in folders], [
            ("project", "项目 B"),
            ("project", "项目 A（重命名）"),
        ])

        with app.db() as conn:
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)", ("space_member", "space-member@example.com", app.hash_password("member123"), "空间成员", app.now()))
        member_token = self.request_json("/api/login", {"email": "space-member@example.com", "password": "member123"})["token"]
        self.request_json(f"/api/folders/{project_a['id']}/invitations", {"email": "space-member@example.com"}, self.token)
        with self.assertRaises(urllib.error.HTTPError) as forbidden_delete:
            self.request_json(f"/api/folders/{project_a['id']}", token=member_token, method="DELETE")
        self.assertEqual(forbidden_delete.exception.code, 404)

        thread = self.request_json(
            "/api/threads", {"title": "项目会议纪要", "folder_id": project_a["id"]}, self.token
        )["thread"]
        self.assertEqual(thread["folder_id"], project_a["id"])

    def test_explicit_web_search_executes_before_model_and_records_sources(self):
        context = {
            "allowed_tool_ids": ["web_search"],
            "tools": [{"id": "web_search", "name": "网页检索"}],
        }
        events = []
        sources = [{"kind": "web", "title": "Agent news", "url": "https://example.com/news", "excerpt": "Latest news"}]
        with patch.object(app.LOCAL_TOOLS, "execute", return_value={"sources": sources, "count": 1, "provider": "mcp:tavily"}) as execute:
            app.execute_authorized_web_search("请联网搜索 Agent 新闻", context, lambda event_type, payload: events.append((event_type, payload)))
        execute.assert_called_once_with("web_search", {"query": "请联网搜索 Agent 新闻"}, {"web_search"})
        self.assertEqual(context["web_search_sources"], sources)
        self.assertEqual(context["web_search_provider"], "mcp:tavily")
        self.assertEqual(context["allowed_tool_ids"], [])
        self.assertEqual(context["tools"], [])
        self.assertEqual([event_type for event_type, _ in events], ["tool_call", "tool_result"])

    def test_preexecuted_mcp_search_never_claims_tools_are_unavailable(self):
        context = {
            "skills": [], "task_tier": "standard", "allowed_tool_ids": [],
            "web_search_sources": [{"title": "天气", "url": "https://example.com/weather", "excerpt": "晴"}],
        }
        prompt = app.build_system_prompt(context)
        self.assertIn("已经通过 Tavily MCP 实际执行网页检索", prompt)
        self.assertNotIn("本次任务未授权工具调用", prompt)

    def test_memory_prompt_truthfully_discloses_the_current_run_injection(self):
        base_context = {"skills": [], "task_tier": "standard", "allowed_tool_ids": []}
        injected = app.build_system_prompt({
            **base_context,
            "memories": [{"id": "memory_1", "kind": "decision", "content": "适度使用二次元用语"}],
        })
        self.assertIn("本次运行实际注入", injected)
        self.assertIn("必须明确回答“是”", injected)
        self.assertIn("memory_1", injected)
        absent = app.build_system_prompt({**base_context, "memories": []})
        self.assertIn("本次运行没有注入长期记忆", absent)
        self.assertIn("必须明确回答“否”", absent)

    def test_realtime_and_url_lookup_requests_are_tool_tasks(self):
        self.assertTrue(app.infer_task_profile("帮我查一下，今天上海的天气")["needs_tools"])
        self.assertTrue(app.infer_task_profile("帮我查一下：https://openai.com/zh-Hant-HK/index/harness-engineering/")["needs_tools"])

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
        self.assertNotIn("片段", answer)
        thread_id = next(event["data"]["thread_id"] for event in events if event["event"] == "meta")
        run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        context = json.loads(run["execution_context"])
        self.assertEqual(context["knowledge_refs"][0]["filename"], "product.md")
        self.assertEqual(context["knowledge_route"], "retrieved")
        self.assertEqual(context["knowledge_match_count"], 1)
        self.assertEqual(context["retrieval_policy"]["version"], "lexical-retrieval-v1")
        self.assertIn("knowledge_retrieved", [event["type"] for event in self.request_json(f"/api/runs/{run['id']}", token=self.token)["events"]])
        thread_context = self.request_json(f"/api/threads/{thread_id}/context", token=self.token)
        self.assertEqual(thread_context["sources"][0]["filename"], "product.md")
        self.assertEqual(thread_context["sources"][0]["position"], 0)

        feedback = self.request_json(
            f"/api/runs/{run['id']}/feedback",
            {"rating": 1, "citation_correct": True},
            self.token,
        )
        self.assertTrue(feedback["citation_correct"])
        answer_feedback = self.request_json(f"/api/runs/{run['id']}/feedback", {"rating": -1, "reason_code": "inaccurate"}, self.token)
        self.assertEqual(answer_feedback["reason_code"], "inaccurate")
        self.assertEqual(self.request_json(f"/api/runs/{run['id']}", token=self.token)["feedback"]["reason_code"], "inaccurate")
        metrics = self.request_json("/api/metrics", token=self.token)
        self.assertEqual(metrics["feedback"]["citation_assessed"], 1)
        self.assertEqual(metrics["feedback"]["citation_accuracy"], 1.0)

        citation_item = context["knowledge_refs"][0]
        detailed_feedback = self.request_json(
            f"/api/runs/{run['id']}/feedback",
            {"rating": -1, "citation_correct": False, "citation_items": [{
                "document_id": citation_item["document_id"], "citation_correct": False,
                "reason_code": "wrong_document", "note": "文档与问题无关",
            }]},
            self.token,
        )
        self.assertEqual(detailed_feedback["citation_items"][0]["reason_code"], "wrong_document")
        run_detail = self.request_json(f"/api/runs/{run['id']}", token=self.token)
        self.assertEqual(len(run_detail["citation_feedback_items"]), 1)
        self.assertEqual(run_detail["citation_feedback_items"][0]["document_id"], citation_item["document_id"])
        self.assertEqual(run_detail["citation_feedback_items"][0]["position"], citation_item["position"])
        metrics = self.request_json("/api/metrics", token=self.token)
        self.assertEqual(metrics["feedback"]["document_citation_accuracy"], 0.0)
        self.assertFalse(metrics["feedback"]["sufficient_for_retrieval_claim"])
        self.assertEqual(metrics["retrieval_policy"]["version"], "lexical-retrieval-v1")
        diagnostics = self.request_json("/api/retrieval-diagnostics", token=self.token)
        self.assertEqual(diagnostics["sample"]["state"], "insufficient")
        self.assertEqual(diagnostics["sample"]["document_feedback_count"], 1)
        self.assertEqual(diagnostics["reason_counts"], {"wrong_document": 1})
        self.assertEqual(diagnostics["documents"][0]["document_id"], citation_item["document_id"])
        self.assertEqual(diagnostics["documents"][0]["risk_level"], "observe")
        self.assertEqual(diagnostics["documents"][0]["reference"]["run_id"], run["id"])
        self.assertEqual(diagnostics["documents"][0]["reference"]["position"], citation_item["position"])
        self.assertIn("coverage", diagnostics["documents"][0]["reference"]["score_breakdown"])
        self.assertEqual(diagnostics["policy_feedback"][0]["retrieval_policy_version"], "lexical-retrieval-v1")
        self.assertEqual(diagnostics["policy_feedback"][0]["state"], "observing")

        generic_events = self.chat({"thread_id": thread_id, "content": "请分析一下这个平台的界面布局"})
        generic_answer = "".join(event["data"].get("content", "") for event in generic_events)
        generic_run = self.request_json(f"/api/threads/{thread_id}/runs", token=self.token)["runs"][0]
        generic_context = json.loads(generic_run["execution_context"])
        self.assertNotIn("参考资料：", generic_answer)
        self.assertEqual(generic_context["knowledge_route"], "not_needed")
        self.assertEqual(generic_context["knowledge_intent"]["reason"], "not_recognized")

        self.request_json(f"/api/knowledge/{document_id}", token=self.token, method="DELETE")
        self.assertEqual(self.request_json(f"/api/knowledge/search?query={quote('北极星指标')}", token=self.token)["results"], [])

    def test_knowledge_citations_show_each_matched_document_once(self):
        answer = app.append_knowledge_sources("回答", [
            {"filename": "通用资料.md", "position": 0, "excerpt": "第一段"},
            {"filename": "通用资料.md", "position": 1, "excerpt": "第二段"},
            {"filename": "项目资料.md", "position": 0, "excerpt": "第三段"},
        ], "retrieved")

        self.assertEqual(answer, "回答\n\n参考资料：通用资料.md、项目资料.md")

    def test_retrieval_policy_candidate_evaluation_publish_and_rollback(self):
        user_id = self.request_json("/api/me", token=self.token)["user"]["id"]
        timestamp = app.now()
        with app.db() as conn:
            conn.executemany("""INSERT INTO citation_feedback_items
                (id, run_id, user_id, document_id, position, citation_correct, reason_code, note, retrieval_policy_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 1, ?, '', 'lexical-retrieval-v1', ?, ?)""", [
                (f"feedback_{index}", f"run_{index}", user_id, f"doc_{index}", "missing_evidence" if index < 3 else "", timestamp, timestamp)
                for index in range(20)
            ])
        suggestions = self.request_json("/api/retrieval-suggestions", token=self.token)["suggestions"]
        self.assertEqual(suggestions[0]["changed_variable"], "limit")
        candidate = self.request_json(f"/api/retrieval-suggestions/{suggestions[0]['id']}/candidate", {}, self.token)["policy"]
        self.assertEqual(candidate["config"]["limit"], 5)
        evaluated = self.request_json(f"/api/retrieval-policies/{candidate['version']}/evaluate", {}, self.token)
        self.assertEqual(evaluated["status"], "verified")
        with app.db() as conn:
            conn.execute("""INSERT INTO retrieval_policies
                (version, config_json, status, parent_version, changed_variable, created_at)
                VALUES ('candidate-bad-neighbors', ?, 'candidate', 'lexical-retrieval-v1', 'neighbor_radius', ?)""", (json.dumps({"limit": 4, "max_excerpt_chars": 900, "max_total_chars": 2800, "neighbor_radius": 0}), app.now()))
        blocked = self.request_json("/api/retrieval-policies/candidate-bad-neighbors/evaluate", {}, self.token)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["experiment"]["decision"], "rollback")
        published = self.request_json(f"/api/retrieval-policies/{candidate['version']}/publish", {}, self.token)
        self.assertEqual(published["active"]["version"], candidate["version"])
        rolled_back = self.request_json("/api/retrieval-policies/rollback", {}, self.token)
        self.assertEqual(rolled_back["active"]["version"], "lexical-retrieval-v1")

    def test_xlsx_knowledge_extraction_preserves_sheet_and_cell_text(self):
        workbook = io.BytesIO()
        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr("xl/workbook.xml", """<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"预算\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>""")
            archive.writestr("xl/_rels/workbook.xml.rels", """<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Target=\"worksheets/sheet1.xml\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\"/></Relationships>""")
            archive.writestr("xl/sharedStrings.xml", """<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><si><t>项目</t></si><si><t>预算</t></si></sst>""")
            archive.writestr("xl/worksheets/sheet1.xml", """<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData><row r=\"1\"><c r=\"A1\" t=\"s\"><v>0</v></c><c r=\"B1\" t=\"s\"><v>1</v></c></row></sheetData></worksheet>""")
        text = app.extract_knowledge_text("budget.xlsx", workbook.getvalue())
        self.assertIn("【工作表：预算】", text)
        self.assertIn("项目 | 预算", text)

    def test_knowledge_upload_validation_checks_mime_signatures_and_archive_budget(self):
        with self.assertRaisesRegex(ValueError, "MIME"):
            app.validate_knowledge_upload("notes.md", "application/pdf", b"plain text")
        with self.assertRaisesRegex(ValueError, "PDF 文件签名"):
            app.validate_knowledge_upload("notes.pdf", "application/pdf", b"not a pdf")
        workbook = io.BytesIO()
        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
        with patch.object(app, "MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "展开"):
                app.validate_knowledge_upload(
                    "budget.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", workbook.getvalue()
                )

    def test_image_knowledge_uses_bounded_local_ocr_without_network(self):
        completed = subprocess.CompletedProcess(["tesseract"], 0, stdout="产品指标：42".encode("utf-8"), stderr=b"")
        with patch.object(app, "TESSERACT_BINARY", "/opt/homebrew/bin/tesseract"), patch.object(app.subprocess, "run", return_value=completed) as run:
            text = app.extract_knowledge_text("指标截图.png", b"\x89PNG\r\n\x1a\nimage")
        self.assertIn("【图片 OCR（本地）：指标截图.png】", text)
        self.assertIn("产品指标：42", text)
        self.assertEqual(run.call_args.kwargs["timeout"], 25)
        self.assertEqual(run.call_args.kwargs["input"], b"\x89PNG\r\n\x1a\nimage")

    def test_knowledge_search_is_strictly_isolated_by_user(self):
        with app.db() as conn:
            conn.execute(
                """INSERT INTO knowledge_documents
                   (id, user_id, filename, storage_path, mime_type, content_hash, size_bytes, chunk_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("private_doc", "other_user", "private.md", "", "text/markdown", "hash", 12, 1, app.now()),
            )
            conn.execute(
                "INSERT INTO knowledge_chunks (id, document_id, position, content) VALUES (?, ?, ?, ?)",
                ("private_chunk", "private_doc", 0, "隔离验证标记只属于另一个用户。"),
            )
        current_user_results = self.request_json(
            f"/api/knowledge/search?query={quote('隔离验证标记')}", token=self.token
        )["results"]
        self.assertEqual(current_user_results, [])
        self.assertEqual(app.search_knowledge("other_user", "隔离验证标记")[0]["document_id"], "private_doc")

    def test_artifact_download_rechecks_current_user_and_hides_local_path(self):
        original_artifact_dir = app.ARTIFACT_DIR
        app.ARTIFACT_DIR = Path(self.temp_dir.name) / "artifacts"
        foreign_file = app.ARTIFACT_DIR / "other_user" / "private.md"
        foreign_file.parent.mkdir(parents=True)
        foreign_file.write_text("private", encoding="utf-8")
        try:
            with app.db() as conn:
                conn.execute("INSERT INTO artifacts (id, user_id, run_id, filename, kind, storage_path, summary, created_at) VALUES (?, ?, '', ?, 'markdown', ?, '', ?)", ("foreign_artifact", "other_user", "private.md", str(foreign_file), app.now()))
            request = urllib.request.Request(
                f"{self.base_url}/api/artifacts/foreign_artifact/download",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(denied.exception.code, 404)
        finally:
            app.ARTIFACT_DIR = original_artifact_dir

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
                "SELECT type, sequence FROM run_events WHERE run_id = 'run_interrupted' AND type = 'run_recovered'"
            ).fetchone()
        self.assertEqual(interrupted["status"], "failed")
        self.assertIn("请重试", interrupted["error"])
        self.assertEqual(waiting["status"], "awaiting_confirmation")
        self.assertEqual(recovery_event["type"], "run_recovered")
        self.assertEqual(recovery_event["sequence"], 2)

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


class ExecutionPlanTests(unittest.TestCase):
    def test_task_frame_generates_a_dynamic_run_plan(self):
        frame = {"frame": {
            "goal": "制定迁移方案",
            "evidence_requirements": [{"id": "e1", "description": "现有系统约束"}],
            "deliverables": [{"id": "d1", "description": "迁移步骤"}, {"id": "d2", "description": "风险清单"}],
        }}
        plan = app.build_execution_plan("制定迁移方案", [], [], frame)
        self.assertEqual([item["id"] for item in plan], ["task_understanding", "evidence_1", "deliverable_1", "deliverable_2", "task_verification"])
        self.assertIn("迁移步骤", plan[2]["title"])


if __name__ == "__main__":
    unittest.main()
