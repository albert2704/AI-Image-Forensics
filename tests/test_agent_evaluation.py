import unittest

from forensics.agent_evaluation import replay_source, CATALOG, validate_replay_rows
from forensics.benchmark import _digest
from forensics.planner import RulePlanner


def rows(scores):
    return {condition: {"score": score, "width": 640, "height": 480, "cache_key": condition,
                        "prediction": {"runtime_seconds": 1.0}} for condition, score in zip(CATALOG, scores)}


class ReplayTests(unittest.TestCase):
    def test_fixed_policy_can_miss_catalog_change(self):
        # Only repeated JPEG changes; fixed uses the other three available tests.
        result = replay_source("fixture", rows([.9, .8, .1, .7, .6]), None, "fixed", 4)
        self.assertTrue(result["reference_instability"])
        self.assertFalse(result["discovered_instability"])
        self.assertEqual(result["detector_tool_calls"], 4)
        self.assertEqual(result["replayed_detector_seconds"], 4)
        self.assertEqual(result["planner_seconds"], 0)

    def test_rule_changes_actions_after_observation(self):
        result = replay_source("fixture", rows([.9, .1, .1, .8, .7]), RulePlanner(), "rule", 4)
        self.assertEqual([d["action"] for d in result["decisions"]][:2], ["jpeg_q85_r1", "resize_s0.9_r1"])
        self.assertTrue(result["discovered_instability"])
        self.assertTrue(result["evidence_references_valid"])

    def test_low_stable_rule_stops_early(self):
        result = replay_source("fixture", rows([.1, .1, .1, .1, .1]), RulePlanner(), "rule", 4)
        self.assertEqual(result["detector_tool_calls"], 2)
        self.assertEqual(result["decisions"][-1]["action"], "finish")
        self.assertFalse(result["reference_instability"])

    def test_planner_failure_is_retained_in_episode(self):
        class FailedPlanner:
            def choose(self, *args):
                raise RuntimeError("fixture failure")
        result = replay_source("fixture", rows([.9, .1, .1, .1, .1]), FailedPlanner(), "local_llm", 4)
        self.assertEqual(result["summary"]["stop_reason"], "planner_failed")
        self.assertEqual(result["detector_tool_calls"], 1)
        self.assertFalse(result["valid_actions"])

    def test_replay_provenance_and_duplicates(self):
        study = {"sources": [{"source_id": "fixture", "sha256": "image-hash"}], "bfree_fingerprint": {"model": "fixture"}, "protocol_hash": "protocol"}
        records = [{"source_id": "fixture", "condition": c, "protocol_hash": "protocol", "model_fingerprint_sha256": _digest(study["bfree_fingerprint"]), "source_sha256": "image-hash", "score": .5, "prediction": {"score": .5}, "detector_id": "bfree"} for c in CATALOG]
        self.assertEqual(len(validate_replay_rows(records, study, ["fixture"])["fixture"]), 5)
        with self.assertRaises(ValueError):
            validate_replay_rows(records + [records[0]], study, ["fixture"])
        with self.assertRaises(ValueError):
            validate_replay_rows([{**records[0], "source_sha256": "changed"}, *records[1:]], study, ["fixture"])
        with self.assertRaises(ValueError):
            validate_replay_rows([{**records[0], "score": float("nan")}, *records[1:]], study, ["fixture"])


if __name__ == "__main__":
    unittest.main()
