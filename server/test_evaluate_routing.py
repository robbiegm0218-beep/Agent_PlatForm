import json
import tempfile
import unittest
from pathlib import Path

from server.evaluate_routing import DEFAULT_SUITE, evaluate_suite, load_suite


class RoutingEvaluationTests(unittest.TestCase):
    def write_suite(self, cases) -> Path:
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False)
        json.dump({"name": "test", "cases": cases}, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return Path(handle.name)

    @staticmethod
    def case(case_id="case", **extra):
        return {"id": case_id, "prompt": "你好", "expected_route": {"task_tier": "quick"}, **extra}

    def test_real_fixture_has_24_unique_cases(self):
        suite = load_suite(DEFAULT_SUITE)
        self.assertEqual(len(suite["cases"]), 24)
        self.assertEqual(len({case["id"] for case in suite["cases"]}), 24)

    def test_rejects_empty_cases_and_duplicate_ids(self):
        with self.assertRaises(ValueError):
            load_suite(self.write_suite([]))
        with self.assertRaises(ValueError):
            load_suite(self.write_suite([self.case(), self.case()]))

    def test_rejects_invalid_optional_overrides(self):
        for extra in ({"task_mode": "ultra"}, {"task_mode": ""}, {"model": ""}, {"model": None}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                load_suite(self.write_suite([self.case(**extra)]))

    def test_all_pass_report(self):
        suite = {"name": "pass", "cases": [self.case()]}

        def route(_prompt, requested_model="auto", requested_task_mode="auto"):
            return {"task_tier": "quick"}

        report = evaluate_suite(suite, route)
        self.assertEqual(report["summary"], {"total": 1, "passed": 1, "failed": 0})
        self.assertEqual(report["mismatches"], [])

    def test_mismatch_report_contains_field_evidence(self):
        suite = {"name": "fail", "cases": [self.case()]}

        def route(_prompt, requested_model="auto", requested_task_mode="auto"):
            return {"task_tier": "deep"}

        report = evaluate_suite(suite, route)
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(report["mismatches"], [
            {"id": "case", "field": "task_tier", "expected": "quick", "actual": "deep"}
        ])


if __name__ == "__main__":
    unittest.main()
