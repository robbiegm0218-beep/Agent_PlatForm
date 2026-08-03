import json
import unittest

from server.evaluate_knowledge_configuration import REPORT_PATH, run
from server.knowledge_configuration_contracts import (
    ConfigurationCapability,
    KnowledgeConfigurationSnapshot,
    capability_matrix,
    configuration_contract_snapshot,
    resolve_retrieval_profile,
)
from server.knowledge_retrieval import RetrievalConfig
from server.retrieval_governance import config_as_dict, config_from_json


class KnowledgeConfigurationContractTests(unittest.TestCase):
    def test_capability_matrix_covers_all_configuration_surfaces(self):
        matrix = capability_matrix()
        self.assertEqual(len(matrix), len({item.capability_id for item in matrix}))
        self.assertEqual(
            {item.area for item in matrix},
            {"user", "processing", "retrieval", "index", "migration", "security"},
        )
        by_id = {item.capability_id: item for item in matrix}
        self.assertEqual(by_id["processing_presets"].writable_roles, ("knowledge_admin", "platform_admin"))
        self.assertEqual(by_id["retrieval_policy"].writable_roles, ("platform_admin",))
        self.assertEqual(by_id["embedding_runtime"].surfaces, ("environment",))
        self.assertEqual(by_id["embedding_jobs"].surfaces, ("ui", "api"))
        self.assertEqual(by_id["historical_migration"].surfaces, ("ui", "api"))
        self.assertEqual(by_id["fts_field_weights"].writable_roles, ())
        self.assertEqual(by_id["user_retrieval_profile"].surfaces, ("ui", "api"))
        self.assertEqual(by_id["user_retrieval_profile"].writable_roles, ("user", "knowledge_admin", "platform_admin"))
        self.assertEqual(by_id["upload_chunk_preset"].source, "user_preference")

    def test_capability_rejects_invalid_role_or_surface(self):
        with self.assertRaisesRegex(ValueError, "入口"):
            ConfigurationCapability(
                "bad", "test", "bad", ("unknown",), ("user",), (),
                "code_boundary", "none", ("value",),
            )
        with self.assertRaisesRegex(ValueError, "写入角色"):
            ConfigurationCapability(
                "bad", "test", "bad", ("api",), ("user",), ("platform_admin",),
                "code_boundary", "none", ("value",),
            )

    def test_configuration_snapshot_rejects_sensitive_keys(self):
        with self.assertRaisesRegex(ValueError, "敏感字段"):
            KnowledgeConfigurationSnapshot(
                role="platform_admin",
                capabilities=(),
                user_preferences={},
                processing={},
                retrieval={},
                index={"embedding_api_key": "must-not-appear"},
                migrations={},
                security={},
            )
        with self.assertRaisesRegex(ValueError, "敏感字段"):
            KnowledgeConfigurationSnapshot(
                role="platform_admin",
                capabilities=(),
                user_preferences={},
                processing={},
                retrieval={},
                index={"provider_base_url": "https://example.invalid"},
                migrations={},
                security={},
            )

    def test_balanced_profile_preserves_active_policy(self):
        base = RetrievalConfig()
        self.assertEqual(resolve_retrieval_profile("balanced", base), base)

    def test_precise_profile_only_tightens_retrieval(self):
        base = RetrievalConfig()
        precise = resolve_retrieval_profile("precise", base)
        self.assertLessEqual(precise.limit, base.limit)
        self.assertLessEqual(precise.candidate_limit, base.candidate_limit)
        self.assertLessEqual(precise.max_total_chars, base.max_total_chars)
        self.assertGreaterEqual(precise.vector_min_score, base.vector_min_score)
        self.assertFalse(precise.rewrite_enabled)

    def test_high_recall_profile_respects_global_feature_switches_and_bounds(self):
        base = RetrievalConfig(hybrid_enabled=False, rewrite_enabled=False, candidate_limit=190)
        high = resolve_retrieval_profile("high_recall", base)
        self.assertFalse(high.hybrid_enabled)
        self.assertFalse(high.rewrite_enabled)
        self.assertLessEqual(high.candidate_limit, 200)
        self.assertGreaterEqual(high.limit, base.limit)
        self.assertEqual(high.vector_min_score, base.vector_min_score)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "预设无效"):
            resolve_retrieval_profile("unbounded")

    def test_retrieval_candidate_relations_are_strictly_validated(self):
        base = config_as_dict(RetrievalConfig())
        with self.assertRaisesRegex(ValueError, "总上下文预算"):
            config_from_json({**base, "max_excerpt_chars": 1200, "max_total_chars": 1000}, strict=True)
        with self.assertRaisesRegex(ValueError, "候选数量"):
            config_from_json({**base, "limit": 10, "candidate_limit": 8}, strict=True)

    def test_contract_snapshot_is_deterministic_and_content_safe(self):
        first = configuration_contract_snapshot()
        second = configuration_contract_snapshot()
        self.assertEqual(first, second)
        serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
        for marker in ("api_key", "base_url", "query_text", "knowledge_text", "/Users/"):
            self.assertNotIn(marker, serialized.lower())
        self.assertFalse(first["content_safety"]["secret_values_exposed"])

    def test_baseline_report_matches_fixed_file_and_quality_gates(self):
        first = run()
        second = run()
        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(REPORT_PATH.read_text(encoding="utf-8")))
        self.assertEqual(first["failures"], [])
        self.assertEqual(first["phase"], "P52-8")
        self.assertTrue(first["production_behavior_changed"])
        self.assertEqual(first["retrieval_baseline"]["cases"], 20)
        self.assertEqual(first["retrieval_baseline"]["recall_at_4"], 1.0)
        self.assertEqual(first["retrieval_baseline"]["top1_accuracy"], 1.0)
        self.assertTrue(all(first["hybrid_targeted_gates"].values()))


if __name__ == "__main__":
    unittest.main()
