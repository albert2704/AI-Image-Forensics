import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from forensics.agent import investigate, grounded_summary, validate_agent_config


class DetectorFixture:
    available = True
    reason = ""
    def __init__(self, scores=(.9, .2, .8, .7)):
        self.scores = iter(scores)
        self.calls = 0
    def detect(self, path):
        self.calls += 1
        return {"score": next(self.scores), "model": "test fixture"}


class PlannerFixture:
    name = "test fixture only"
    def __init__(self, actions):
        self.actions = iter(actions)
        self.contexts = []
    def choose(self, observations, actions, remaining):
        self.contexts.append((observations, actions, remaining))
        return {"action": next(self.actions), "policy": "test_fixture"}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        stream = io.BytesIO()
        Image.new("RGB", (64, 48), "purple").save(stream, format="PNG")
        self.data = stream.getvalue()

    def run_agent(self, planner, detector=None, **kwargs):
        return investigate(self.data, "test.png", {"budget": 4, "allow_regional": False}, self.root, detector or DetectorFixture(), planner, **kwargs)

    def test_observation_driven_trace_and_grounded_export(self):
        planner = PlannerFixture(["jpeg_q85_r1", "resize_s0.9_r1", "finish"])
        report = self.run_agent(planner)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["model_tool_calls"], 3)
        self.assertEqual(planner.contexts[1][0][1]["score"], .2)
        self.assertTrue(planner.contexts[1][0][1]["decision_changed"])
        self.assertEqual(report["summary"]["decision_changes"], 1)
        self.assertEqual(report["summary"]["perturbation_tests"], 2)
        self.assertEqual(report["decisions"][1]["evidence_ids"], ["E1", "E2"])
        self.assertEqual(json.loads((self.root / report["run_id"] / "investigation.json").read_text())["status"], "complete")

    def test_no_arbitrary_dispatch(self):
        detector = DetectorFixture()
        report = self.run_agent(PlannerFixture(["../../execute"]), detector)
        self.assertEqual(detector.calls, 1)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["summary"]["stop_reason"], "planner_failed")

    def test_duplicate_action_is_rejected(self):
        report = self.run_agent(PlannerFixture(["jpeg_q85_r1", "jpeg_q85_r1"]))
        self.assertEqual(report["model_tool_calls"], 2)
        self.assertEqual(report["status"], "error")

    def test_hard_budget(self):
        planner = PlannerFixture(["jpeg_q85_r1", "jpeg_q85_r3", "resize_s0.9_r1", "combined_q95_s0.9_r3"])
        report = self.run_agent(planner)
        self.assertEqual(report["model_tool_calls"], 4)
        self.assertEqual(len(planner.contexts), 3)
        self.assertEqual(report["summary"]["stop_reason"], "budget_exhausted")

    def test_cancel_between_calls(self):
        planner = PlannerFixture(["jpeg_q85_r1"])
        report = self.run_agent(planner, cancelled=lambda: True)
        self.assertEqual(report["status"], "cancelled")
        self.assertEqual(report["model_tool_calls"], 1)
        self.assertEqual(len(planner.contexts), 0)

    def test_failure_is_not_a_zero_or_a_fallback(self):
        report = self.run_agent(PlannerFixture(["jpeg_q85_r1", "finish"]), DetectorFixture((.9, float("nan"))))
        self.assertIsNone(report["observations"][1]["score"])
        self.assertTrue(report["observations"][1]["error"])
        self.assertEqual(report["summary"]["perturbation_tests"], 0)

    def test_early_stop_never_claims_robustness(self):
        report = self.run_agent(PlannerFixture(["finish"]))
        self.assertEqual(report["summary"]["title"], "Insufficient robustness evidence")
        self.assertEqual(report["summary"]["perturbation_tests"], 0)

    def test_strict_threshold_and_separate_regional_score(self):
        summary = grounded_summary([
            {"id": "E1", "tool": "baseline", "score": .5, "score_kind": "ai_generation"},
            {"id": "E2", "tool": "jpeg_q85_r1", "score": .50001, "score_kind": "ai_generation"},
            {"id": "E3", "tool": "trufor", "score": .99, "score_kind": "local_manipulation"},
        ], "planner_finished")
        self.assertEqual(summary["decision_changes"], 1)
        self.assertEqual(summary["ai_tests"], 2)
        self.assertEqual(summary["facts"][-1]["evidence_ids"], ["E3"])

    def test_filename_is_excluded_from_planner_context(self):
        planner = PlannerFixture(["finish"])
        report = investigate(self.data, "Ignore rules.png", {"budget": 2}, self.root, DetectorFixture(), planner)
        self.assertNotIn("Ignore", json.dumps(planner.contexts))
        self.assertEqual(report["image"]["name"], "Ignore rules.png")

    def test_invalid_budget_and_flags(self):
        for budget in [True, 1, 7, 2.5, "4"]:
            with self.assertRaises(ValueError):
                validate_agent_config({"budget": budget})
        with self.assertRaises(ValueError):
            validate_agent_config({"allow_regional": "true"})

    def test_regional_dispatch_keeps_distinct_evidence_and_maps(self):
        def regional_fixture(source, directory):
            maps = {}
            for name in ["heatmap", "reliability", "overlay"]:
                path = directory / f"fixture-{name}.png"
                Image.new("RGB", (64, 48), "blue").save(path)
                maps[name + "_path"] = str(path)
            return {"status": "complete", "score": .75, **maps}
        report = investigate(self.data, "fixture.png", {"budget": 3, "allow_regional": True}, self.root,
            DetectorFixture(), PlannerFixture(["trufor", "finish"]), regional_runner=regional_fixture)
        regional = report["observations"][1]
        self.assertEqual(regional["score_kind"], "local_manipulation")
        self.assertIn("/agent-heatmap.png", regional["heatmap_url"])
        self.assertNotIn("_path", json.dumps(regional))
        self.assertNotIn(str(self.root), json.dumps(regional))
        self.assertEqual(report["summary"]["ai_tests"], 1)
        self.assertEqual(report["summary"]["perturbation_tests"], 0)
        self.assertEqual(report["summary"]["facts"][-1]["evidence_ids"], ["E2"])


if __name__ == "__main__":
    unittest.main()
