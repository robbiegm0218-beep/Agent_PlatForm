import unittest

from server.evidence_service import append_authorized_observations, append_context_sources, build_knowledge_ledger, parse_model_assessment, rewrite_queries


class EvidenceServiceTests(unittest.TestCase):
    def test_result_is_not_sufficient_when_a_specific_requirement_is_missing(self):
        frame = {"evidence_requirements": [
            {"id": "e_policy", "description": "报销制度流程", "preferred_sources": ["knowledge"]},
            {"id": "e_limit", "description": "报销额度规则", "preferred_sources": ["knowledge"]},
        ]}
        refs = [{"document_id": "d1", "position": 0, "matched_terms": ["报销", "制度", "流程"], "score": 4}]
        ledger = build_knowledge_ledger(frame, refs, knowledge_needed=True)
        self.assertEqual(ledger["decision"], "retrieve_more")
        self.assertEqual(ledger["missing_requirement_ids"], ["e_limit"])

    def test_generic_legacy_requirement_is_covered_by_permitted_reference(self):
        ledger = build_knowledge_ledger(None, [{"document_id": "d1", "position": 0, "matched_terms": ["制度"], "score": 3}], knowledge_needed=True)
        self.assertEqual(ledger["decision"], "sufficient")
        self.assertTrue(ledger["items"][0]["permission_checked"])

    def test_rewrites_are_bounded_and_do_not_use_original_query(self):
        frame = {"evidence_requirements": [{"id": "e1", "description": "报销额度规则", "preferred_sources": ["knowledge"]}]}
        ledger = {"missing_requirement_ids": ["e1"]}
        self.assertLessEqual(len(rewrite_queries(frame, ledger, "报销制度")), 2)

    def test_context_sources_are_metadata_only_and_do_not_cover_missing_knowledge(self):
        frame = {"evidence_requirements": [{"id": "e1", "description": "核对制度", "preferred_sources": ["knowledge"]}]}
        ledger = build_knowledge_ledger(frame, [], knowledge_needed=True)
        updated = append_context_sources(ledger, has_user_input=True, memory_ids=["memory_1"])
        self.assertEqual(updated["requirements"][0]["status"], "missing")
        self.assertEqual({item["source_type"] for item in updated["items"]}, {"user", "memory"})
        self.assertNotIn("核对制度", str(updated))

    def test_authorized_tool_observation_never_retains_result_body(self):
        ledger = build_knowledge_ledger(None, [], knowledge_needed=True)
        updated = append_authorized_observations(ledger, [{
            "source_type": "tool", "source_id": "web_search:call_1", "supports": ["e_legacy_knowledge"],
            "result": "不应写入账本的原始工具正文",
        }])
        self.assertEqual(updated["items"][0]["source_id"], "web_search:call_1")
        self.assertNotIn("原始工具正文", str(updated))

    def test_new_source_reassesses_coverage_but_wrong_source_type_cannot_cover(self):
        frame = {"evidence_requirements": [{"id": "e1", "description": "外部依据", "preferred_sources": ["web"]}]}
        ledger = build_knowledge_ledger(frame, [], knowledge_needed=True)
        self.assertEqual(ledger["decision"], "retrieve_more")
        tool_only = append_authorized_observations(ledger, [{"source_type": "tool", "source_id": "search:1", "supports": ["e1"]}])
        self.assertEqual(tool_only["requirements"][0]["status"], "missing")
        covered = append_authorized_observations(tool_only, [{"source_type": "web", "source_id": "https://example.test", "supports": ["e1"], "freshness": "current"}])
        self.assertEqual(covered["requirements"][0]["status"], "covered")
        self.assertEqual(covered["decision"], "sufficient")

    def test_model_cannot_promote_known_gap_to_sufficient(self):
        ledger = {"missing_requirement_ids": ["e1"]}
        with self.assertRaises(ValueError):
            parse_model_assessment('{"decision":"sufficient","missing_requirement_ids":[]}', ledger)

    def test_authorized_cross_source_observations_keep_only_metadata(self):
        ledger = append_authorized_observations({"items": []}, [{"source_type": "web", "source_id": "https://example.test/a", "supports": ["e1"], "freshness": "current"}, {"source_type": "workspace", "source_id": "README.md", "supports": ["e1"]}])
        self.assertEqual([item["source_type"] for item in ledger["items"]], ["web", "workspace"])
        self.assertNotIn("content", ledger["items"][0])
