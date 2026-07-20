"""Chat request and thread-access domain service.

The HTTP/SSE adapter remains in ``app.py`` while chat lifecycle logic is moved
here incrementally so existing event and database contracts stay stable.
"""
from __future__ import annotations

import json

from server.tool_approval import approval_preview
from server.evidence_service import append_context_sources


class ChatService:
    def __init__(self, db_factory=None, now=None, new_id=None):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id

    def validate_request(self, payload: dict, model_catalog, resolve_execution_modes) -> dict:
        content = str(payload.get("content", "")).strip()
        if not content:
            raise ValueError("消息不能为空")
        requested_model = payload.get("model", "auto")
        if requested_model not in {"auto", *model_catalog}:
            raise ValueError("模型不可用")
        requested_task_mode = payload.get("task_mode", "auto")
        if requested_task_mode not in {"auto", "quick", "standard", "deep"}:
            raise ValueError("任务档位无效")
        requested_skill_ids = payload.get("skill_ids")
        if requested_skill_ids is not None and (
            not isinstance(requested_skill_ids, list) or not all(isinstance(skill_id, str) for skill_id in requested_skill_ids)
        ):
            raise ValueError("技能参数无效")
        return {
            "content": content,
            "thread_id": str(payload.get("thread_id", "")),
            "folder_id": str(payload.get("folder_id", "")),
            "retry": bool(payload.get("retry")),
            "requested_model": requested_model,
            "requested_task_mode": requested_task_mode,
            "requested_skill_ids": requested_skill_ids,
            "execution_modes": resolve_execution_modes(payload),
        }

    def get_editable_thread(self, conn, thread_id: str, user_id: str):
        if not thread_id:
            return None, False
        thread = conn.execute("SELECT * FROM threads WHERE id = ? AND user_id = ?", (thread_id, user_id)).fetchone()
        if thread:
            return thread, False
        shared = conn.execute("""SELECT threads.id FROM threads WHERE threads.id = ? AND threads.folder_id != ''
            AND EXISTS (SELECT 1 FROM space_members WHERE space_members.space_id = threads.folder_id AND space_members.user_id = ?)""", (thread_id, user_id)).fetchone()
        return None, bool(shared)

    def freeze_execution_context(self, conn, *, user_id: str, thread_id: str, content: str,
                                 task_profile: dict, execution_modes: dict, requested_skill_ids,
                                 requested_active_skills, dependencies: dict):
        """Build the immutable per-run context before the Run row is created."""
        structured_context = dependencies["refresh_structured_context"](conn, thread_id)
        active_skills = requested_active_skills if requested_active_skills is not None else dependencies["enabled_skills"](user_id, thread_id)
        intent_plan = dependencies["plan_intent"](content, task_profile)
        needs_knowledge = execution_modes["knowledge"] == "required" or (
            execution_modes["knowledge"] == "auto" and intent_plan["knowledge_needed"]
        )
        project_row = conn.execute("SELECT folder_id FROM threads WHERE id = ?", (thread_id,)).fetchone()
        project_space_id = project_row["folder_id"] if project_row else ""
        knowledge_refs, retrieval_trace = dependencies["retrieve_knowledge"](user_id, content, intent_plan, project_space_id) if needs_knowledge else ([], {})
        memories = dependencies["load_memories"](conn, user_id, thread_id, content)
        execution_context = dependencies["build_execution_context"](
            user_id, task_profile, active_skills, requested_skill_ids, content, knowledge_refs, execution_modes, intent_plan,
        )
        execution_context["structured_context"] = dependencies["select_structured_context"](structured_context, content)
        execution_context["memories"] = memories
        execution_context["space_context"] = dependencies["load_space_context"](conn, user_id, thread_id)
        execution_context["retrieval_trace"] = retrieval_trace
        execution_context["route_summary"]["memory_count"] = len(memories)
        planner = dependencies.get("plan_task_frame")
        if planner:
            task_frame = planner(content, task_profile, intent_plan, execution_modes, execution_context["structured_context"])
            if task_frame:
                execution_context["task_frame"] = task_frame
                execution_context.setdefault("model_usage", {})["planner"] = {
                    "model": execution_context.get("model_roles", {}).get("planner_model", task_profile["model"]),
                    "calls": 1 if task_frame.get("status") == "model" else 0,
                    "duration_ms": task_frame.get("duration_ms", 0), "token_estimate": task_frame.get("token_estimate", 0),
                }
        assess_evidence = dependencies.get("assess_knowledge_evidence")
        if assess_evidence:
            knowledge_refs, retrieval_trace, evidence_ledger = assess_evidence(
                user_id, content, intent_plan, project_space_id,
                (execution_context.get("task_frame") or {}).get("frame"), knowledge_refs, retrieval_trace, task_profile,
            )
            execution_context["knowledge_refs"] = knowledge_refs
            execution_context["knowledge_match_count"] = len(knowledge_refs)
            execution_context["route_summary"]["knowledge_matches"] = len(knowledge_refs)
            execution_context["retrieval_trace"] = retrieval_trace
            if evidence_ledger:
                evidence_ledger = append_context_sources(
                    evidence_ledger, has_user_input=bool(content.strip()),
                    memory_ids=[str(item.get("id", "")) for item in memories if isinstance(item, dict)],
                )
                execution_context["evidence_ledger"] = evidence_ledger
        build_orchestrator_trace = dependencies.get("build_orchestrator_trace")
        if build_orchestrator_trace:
            trace = build_orchestrator_trace(task_profile, execution_context)
            if trace:
                execution_context["orchestrator_trace"] = trace
        return execution_context, active_skills, intent_plan, knowledge_refs, retrieval_trace, memories

    def create_run_record(self, conn, *, thread_id: str, content: str, execution_context: dict,
                          active_skills: list[dict], memories: list[dict], knowledge_refs: list[dict],
                          retrieval_trace: dict, task_profile: dict, artifact_kind: str,
                          execution_plan: list[dict], dependencies: dict) -> str:
        """Persist the immutable run ledger before any SSE execution begins."""
        now, new_id, append_event, runtime = (dependencies[key] for key in ("now", "new_id", "append_event", "runtime"))
        run_id = new_id("run")
        conn.execute("""INSERT INTO runs (id, thread_id, status, model, started_at, skill_snapshot, execution_context, plan_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (run_id, thread_id, "running", execution_context["model"], now(),
            dependencies["json"].dumps(active_skills, ensure_ascii=False), dependencies["json"].dumps(execution_context, ensure_ascii=False),
            dependencies["json"].dumps(execution_plan, ensure_ascii=False)))
        conn.executemany("INSERT INTO memory_usage (run_id, memory_id, used_at) VALUES (?, ?, ?)", [(run_id, item["id"], now()) for item in memories])
        append_event(conn, run_id, "started")
        append_event(conn, run_id, "execution_context", {"model": execution_context["model"], "task_tier": execution_context["task_tier"], "tool_ids": execution_context["allowed_tool_ids"], "tool_route_confidence": execution_context["tool_route_confidence"], "tool_route_reason": execution_context["tool_route_reason"], "execution_modes": execution_context["execution_modes"], "knowledge_matches": len(knowledge_refs), "memory_count": len(memories), "intent_plan": execution_context["intent_plan"]})
        append_event(conn, run_id, "skill_routed", {"route": execution_context["skill_route"], "skills": [skill["name"] for skill in active_skills]})
        append_event(conn, run_id, "reasoning_summary", {"items": dependencies["reasoning_summary"](execution_context)})
        task_frame = execution_context.get("task_frame")
        if task_frame:
            append_event(conn, run_id, "task_frame_planned", {
                "planner_version": task_frame["planner_version"], "mode": task_frame["mode"],
                "eligible": task_frame["eligible"], "status": task_frame["status"],
                "fallback_reason": task_frame["fallback_reason"], "duration_ms": task_frame["duration_ms"],
                "token_estimate": task_frame["token_estimate"], "summary": task_frame["summary"],
            })
        evidence_ledger = execution_context.get("evidence_ledger")
        if evidence_ledger:
            append_event(conn, run_id, "evidence_assessed", {
                "mode": execution_context.get("retrieval_trace", {}).get("evidence_mode", "shadow"),
                "summary": dependencies["evidence_summary"](evidence_ledger),
            })
        for transition in execution_context.get("orchestrator_trace", []):
            append_event(conn, run_id, "orchestrator_transition", {"mode": "shadow", **transition})
        knowledge_event = "knowledge_retrieved" if knowledge_refs else ("knowledge_no_match" if task_profile["needs_knowledge"] else "knowledge_not_needed")
        append_event(conn, run_id, knowledge_event, {"count": len(knowledge_refs), "intent": task_profile["knowledge_intent"]["reason"]})
        if retrieval_trace:
            append_event(conn, run_id, "knowledge_retrieval_assessed", retrieval_trace)
            if retrieval_trace.get("retry_query"):
                append_event(conn, run_id, "knowledge_retrieval_retried", {"query": retrieval_trace["retry_query"], "matches": retrieval_trace["retry_matches"]})
        append_event(conn, run_id, "plan_created", {"steps": execution_plan})
        conn.executemany("""INSERT INTO run_steps (id, run_id, position, title, status, requires_confirmation, input_json, output_json,
            idempotency_key, timeout_seconds, max_retries, retry_count, resume_policy, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""", [
            (new_id("step"), run_id, index, step["title"], "awaiting_confirmation" if artifact_kind and index == 1 else "pending",
             1 if step.get("requires_confirmation") else 0, dependencies["json"].dumps({"task_preview": content[:160], "phase": step.get("phase", "generating")}, ensure_ascii=False), "{}",
             f"{run_id}:{step['id']}", step.get("timeout_seconds", 30), step.get("max_retries", 0), step.get("resume_policy", "resume_from_contract"), now())
            for index, step in enumerate(execution_plan, start=1)
        ])
        if artifact_kind:
            runtime.transition_run(conn, run_id, "awaiting_confirmation")
            runtime.transition_phase(conn, run_id, "awaiting_confirmation", detail={"step": "confirmation"})
            approval = approval_preview(
                tool_id="create_artifact", tool_name="创建本地文件", risk_level="local_write",
                arguments={"kind": artifact_kind}, visible_argument_keys={"kind"},
                effect_summary=f"在本机受控产物目录创建一个 {artifact_kind} 文件",
                rollback_summary="可在产物列表中删除该文件；删除不会影响原始对话和运行记录",
                idempotency_key=f"artifact:{run_id}:{artifact_kind}",
            )
            self.create_tool_approval_request(
                conn, run_id=run_id, position=1, step_id="step_1", approval=approval,
                operation_id=f"operation_{run_id}", new_id=new_id, now=now,
            )
            append_event(conn, run_id, "confirmation_requested", {"kind": artifact_kind, "target": "data/artifacts", "risk_level": "local_write", "tool_id": "create_artifact", "rollback_summary": "可在产物列表中删除该文件；删除不会影响原始对话和运行记录", "idempotency_key": f"artifact:{run_id}:{artifact_kind}"})
        elif knowledge_refs or execution_context["knowledge_route"] == "required_no_match":
            runtime.transition_phase(conn, run_id, "retrieving", detail={"knowledge_matches": len(knowledge_refs)})
        return run_id, knowledge_event

    @staticmethod
    def create_tool_approval_request(conn, *, run_id: str, position: int, step_id: str, approval: dict,
                                     operation_id: str, new_id, now) -> str:
        """Persist one sanitized risky-tool request for a resumable Run.

        Callers must obtain ``approval`` from ``tool_approval.approval_preview``;
        that keeps raw parameters outside this durable user-facing record.
        """
        approval_id = new_id("approval")
        conn.execute("""INSERT INTO run_approval_requests (id, run_id, position, step_id, request, status, created_at, operation_id, risk_level, tool_id, arguments_json, effect_summary, rollback_summary, idempotency_key)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""", (
            approval_id, run_id, position, step_id, approval["request"], now(), operation_id,
            approval["risk_level"], approval["tool_id"], approval["arguments_json"],
            approval["effect_summary"], approval["rollback_summary"], approval["idempotency_key"],
        ))
        return approval_id

    def record_runtime_event(self, run_id: str, event_type: str, payload: dict, dependencies: dict) -> None:
        with self.db_factory() as conn:
            phase = conn.execute("SELECT run_phase FROM runs WHERE id = ?", (run_id,)).fetchone()
            current_phase = phase["run_phase"] if phase else ""
            runtime = dependencies["runtime"]
            if event_type == "tool_call" and current_phase in {"planning", "retrieving", "generating"}:
                runtime.transition_phase(conn, run_id, "executing_tool", detail={"tool_id": payload.get("tool_id", "")})
                self._advance_run_step(conn, run_id, "executing_tool", {"tool_id": payload.get("tool_id", "")})
            elif event_type == "reflection_started" and current_phase in {"generating", "executing_tool"}:
                runtime.transition_phase(conn, run_id, "reflecting")
                self._advance_run_step(conn, run_id, "reflecting", {})
            dependencies["append_event"](conn, run_id, event_type, payload)

    def _advance_run_step(self, conn, run_id: str, phase: str, detail: dict) -> None:
        """Move the saved plan at an observed runtime boundary, without inventing work."""
        running = conn.execute("SELECT id FROM run_steps WHERE run_id = ? AND status = 'running' ORDER BY position LIMIT 1", (run_id,)).fetchone()
        if running:
            conn.execute("UPDATE run_steps SET status = ?, output_json = ?, updated_at = ? WHERE id = ?", ("completed", json.dumps({"status": "completed", "observed_phase": phase}, ensure_ascii=False), self.now(), running["id"]))
        next_step = None
        for candidate in conn.execute("SELECT id, input_json FROM run_steps WHERE run_id = ? AND status = 'pending' ORDER BY position", (run_id,)).fetchall():
            try:
                if json.loads(candidate["input_json"] or "{}").get("phase") == phase:
                    next_step = candidate
                    break
            except json.JSONDecodeError:
                continue
        if next_step:
            conn.execute("UPDATE run_steps SET status = ?, output_json = ?, updated_at = ? WHERE id = ?", ("running", json.dumps({"status": "running", **detail}, ensure_ascii=False), self.now(), next_step["id"]))

    def finalize_run(self, run_id: str, thread_id: str, content: str, answer: str, execution_context: dict, reflection: dict, dependencies: dict) -> None:
        with self.db_factory() as conn:
            execution_context.setdefault("model_usage", {})["executor"] = {
                "model": execution_context.get("model_roles", {}).get("executor_model", execution_context["model"]),
                "calls": 1, "input_token_estimate": dependencies["estimate_tokens"](content), "output_token_estimate": dependencies["estimate_tokens"](answer),
            }
            conn.execute("INSERT INTO messages (id, thread_id, run_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)", (self.new_id("msg"), thread_id, run_id, "assistant", answer, self.now()))
            dependencies["refresh_context"](conn, thread_id)
            runtime = dependencies["runtime"]
            runtime.transition_run(conn, run_id, "completed")
            phase = conn.execute("SELECT run_phase FROM runs WHERE id = ?", (run_id,)).fetchone()
            if phase and phase["run_phase"] not in {"completed", "failed", "cancelled"}:
                runtime.transition_phase(conn, run_id, "completed")
            conn.execute("UPDATE runs SET execution_context = ?, reflection_snapshot = ?, input_tokens_estimate = ?, output_tokens_estimate = ?, tool_call_count = ? WHERE id = ?", (dependencies["json"].dumps(execution_context, ensure_ascii=False), dependencies["json"].dumps(reflection, ensure_ascii=False), dependencies["estimate_tokens"](content), dependencies["estimate_tokens"](answer), conn.execute("SELECT COUNT(*) AS count FROM run_events WHERE run_id = ? AND type = 'tool_call'", (run_id,)).fetchone()["count"], run_id))
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (self.now(), thread_id))
            output = dependencies["json"].dumps({"answer_chars": len(answer), "status": "completed"})
            conn.execute("UPDATE run_steps SET status = ?, output_json = ?, updated_at = ? WHERE run_id = ? AND status = 'running'", ("completed", output, self.now(), run_id))
            # A tool step that was never called is shown as skipped, rather
            # than as a completed action. Other pending steps are completed by
            # the final generation pass.
            pending = conn.execute("SELECT id, input_json FROM run_steps WHERE run_id = ? AND status = 'pending'", (run_id,)).fetchall()
            for step in pending:
                try:
                    phase = json.loads(step["input_json"] or "{}").get("phase")
                except json.JSONDecodeError:
                    phase = None
                if phase == "executing_tool":
                    step_status, step_output = "skipped", dependencies["json"].dumps({"status": "skipped", "reason": "模型判断无需调用授权工具"}, ensure_ascii=False)
                else:
                    step_status, step_output = "completed", output
                conn.execute("UPDATE run_steps SET status = ?, output_json = ?, updated_at = ? WHERE id = ?", (step_status, step_output, self.now(), step["id"]))
            dependencies["append_event"](conn, run_id, "completed", {"length": len(answer)})

    def cancel_run(self, run_id: str, user_id: str, dependencies: dict) -> str:
        with self.db_factory() as conn:
            run = conn.execute("SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id WHERE runs.id = ? AND threads.user_id = ?", (run_id, user_id)).fetchone()
            if not run:
                return "not_found"
            if run["status"] not in {"running", "awaiting_confirmation"}:
                return "not_cancellable"
            context = dependencies["json"].loads(run["execution_context"] or "{}")
            if run["status"] == "running" and context.get("artifact_request"):
                return "unsafe"
            if run["status"] == "awaiting_confirmation":
                conn.execute("UPDATE run_confirmations SET status = ?, decision = ?, resolved_at = ? WHERE run_id = ? AND status = 'pending'", ("cancelled", "用户取消", self.now(), run_id))
                conn.execute("UPDATE run_approval_requests SET status = ?, decision = ?, resolved_at = ? WHERE run_id = ? AND status = 'pending'", ("cancelled", "用户取消", self.now(), run_id))
            runtime = dependencies["runtime"]
            runtime.transition_run(conn, run_id, "cancelled")
            phase = conn.execute("SELECT run_phase FROM runs WHERE id = ?", (run_id,)).fetchone()
            if phase and phase["run_phase"] not in {"cancelled", "completed", "failed"}:
                runtime.transition_phase(conn, run_id, "cancelled", detail={"reason": "user_cancelled"})
            conn.execute("UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND status IN ('pending', 'running', 'awaiting_confirmation')", ("cancelled", self.now(), run_id))
            dependencies["append_event"](conn, run_id, "cancelled", {"source": "user"})
            return "cancelled"

    def resolve_confirmation(self, run_id: str, user_id: str, approved: bool, dependencies: dict):
        with self.db_factory() as conn:
            run = conn.execute("SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id WHERE runs.id = ? AND threads.user_id = ?", (run_id, user_id)).fetchone()
            approvals = conn.execute("SELECT * FROM run_approval_requests WHERE run_id = ? ORDER BY position ASC", (run_id,)).fetchall()
            confirmation = next((item for item in approvals if item["status"] == "pending"), None) or (approvals[-1] if approvals else None)
            confirmation = confirmation or conn.execute("SELECT * FROM run_confirmations WHERE run_id = ?", (run_id,)).fetchone()
            if not run or not confirmation:
                return "not_found", None
            if confirmation["status"] != "pending" or run["status"] != "awaiting_confirmation":
                return "handled", None
            status = "approved" if approved else "rejected"
            if "id" in confirmation.keys():
                conn.execute("UPDATE run_approval_requests SET status = ?, decision = ?, resolved_at = ? WHERE id = ?", (status, "用户批准" if approved else "用户拒绝", self.now(), confirmation["id"]))
            else:
                conn.execute("UPDATE run_confirmations SET status = ?, decision = ?, resolved_at = ? WHERE run_id = ?", (status, "用户批准" if approved else "用户拒绝", self.now(), run_id))
            if not approved:
                runtime = dependencies["runtime"]
                runtime.transition_run(conn, run_id, "cancelled")
                runtime.transition_phase(conn, run_id, "cancelled", detail={"reason": "confirmation_rejected"})
                conn.execute("UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND status = 'awaiting_confirmation'", ("cancelled", self.now(), run_id))
            dependencies["append_event"](conn, run_id, "confirmation_resolved", {"approved": approved})
            if not approved:
                return "rejected", None
            next_approval = conn.execute("SELECT * FROM run_approval_requests WHERE run_id = ? AND status = 'pending' ORDER BY position ASC LIMIT 1", (run_id,)).fetchone()
            if next_approval:
                dependencies["append_event"](conn, run_id, "confirmation_requested", {"position": next_approval["position"], "tool_id": next_approval["tool_id"]})
            return ("next", next_approval) if next_approval else ("execute", None)

    def fail_run(self, run_id: str, error: str, dependencies: dict) -> bool:
        with self.db_factory() as conn:
            status = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if status and status["status"] == "cancelled":
                return False
            runtime = dependencies["runtime"]
            runtime.transition_run(conn, run_id, "failed", error=error)
            phase = conn.execute("SELECT run_phase FROM runs WHERE id = ?", (run_id,)).fetchone()
            if phase and phase["run_phase"] not in {"completed", "failed", "cancelled"}:
                runtime.transition_phase(conn, run_id, "failed", detail={"reason": "runtime_error"})
            dependencies["append_event"](conn, run_id, "failed", {"error": error})
            conn.execute("UPDATE run_steps SET status = ?, error = ?, output_json = ?, updated_at = ? WHERE run_id = ? AND status = 'running'", ("failed", error, dependencies["json"].dumps({"error": error[:500], "status": "failed"}), self.now(), run_id))
            return True

    def resume_confirmed_operation(self, run_id: str, user_id: str, executor):
        """Resume the approved operation from the same persisted Run."""
        return executor(run_id, user_id)

    def resume_confirmed_artifact(self, run_id: str, user_id: str, executor):
        """Compatibility name for the file-artifact operation."""
        return self.resume_confirmed_operation(run_id, user_id, executor)
