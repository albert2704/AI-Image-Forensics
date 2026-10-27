"""Independently audit completed policy episodes without project code imports.

Reconstruct decisions from the frozen score catalog and raw episode observations.
This verifies accounting and evidence consistency, not language-model quality.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "output" / "agent-evaluation"
OUTPUT = ROOT / "output" / "verification" / "independent-policy-check.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: actual={actual!r}, expected={expected!r}")


def close(actual, expected, message):
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12):
        raise AssertionError(f"{message}: actual={actual!r}, expected={expected!r}")


def main():
    protocol_path = DIRECTORY / "protocol.json"
    protocol = read(protocol_path)
    same(digest({key: value for key, value in protocol.items() if key != "protocol_hash"}), protocol["protocol_hash"], "Agent protocol digest")
    study = read(Path(protocol["study_protocol_path"]))
    same(study["protocol_hash"], protocol["study_protocol_hash"], "Study identity")
    same(protocol["budget"], 4, "Prespecified budget")
    same(protocol["threshold"], .5, "Prespecified threshold")
    same(protocol["allow_regional"], False, "Regional replay disabled")
    source_ids, policies = protocol["source_ids"], protocol["policies"]
    same(len(source_ids), 24, "Planned source count")
    same(len(set(source_ids)), 24, "Unique planned source count")
    same(set(policies), {"fixed", "rule", "local_llm"}, "Planned policies")
    study_sources = {source["source_id"]: source for source in study["sources"]}
    same({study_sources[source]["split"] for source in source_ids}, {"test"}, "Held-out subset")
    same(Counter(study_sources[source]["label"] for source in source_ids), Counter({0: 12, 1: 12}), "Subset labels")
    group_members = Counter(study_sources[source]["group_id"] for source in source_ids)
    same(len(group_members), 12, "Subset groups")
    same(set(group_members.values()), {2}, "Paired group coverage")
    for group in group_members:
        same(sorted(study_sources[source]["label"] for source in source_ids if study_sources[source]["group_id"] == group), [0, 1], "Real/generated members retained together")
    same(Counter(study_sources[source]["generator"] for source in source_ids if study_sources[source]["label"] == 1),
         Counter({"dalle3": 3, "firefly": 3, "midjourney-v5": 3, "stable-diffusion-xl": 3}), "Generator strata")
    snapshot_path = DIRECTORY / "replay-inputs.json"
    snapshot = read(snapshot_path)
    same(digest({key: value for key, value in snapshot.items() if key != "input_sha256"}), snapshot["input_sha256"], "Replay snapshot digest")
    same(snapshot["protocol_hash"], protocol["protocol_hash"], "Replay snapshot protocol")
    lookup = {(row["source_id"], row["condition"]): row for row in snapshot["rows"]}
    expected_keys = {(source, condition) for source in source_ids for condition in protocol["catalog"]}
    same(set(lookup), expected_keys, "Complete replay catalog")
    same(len(snapshot["rows"]), len(expected_keys), "No duplicate replay input rows")
    for row in lookup.values():
        if isinstance(row["score"], bool) or not math.isfinite(row["score"]) or not 0 <= row["score"] <= 1:
            raise AssertionError("Invalid frozen replay score")
        same(row["source_sha256"], study_sources[row["source_id"]]["sha256"], "Replay source byte identity")
        same(row["protocol_hash"], study["protocol_hash"], "Replay detector study identity")
    reference = {source: any((lookup[source, condition]["score"] > .5) != (lookup[source, "baseline"]["score"] > .5)
                            for condition in protocol["catalog"] if condition != "baseline") for source in source_ids}
    summary_path = DIRECTORY / "summary.json"
    summary = read(summary_path)
    same(summary["protocol_hash"], protocol["protocol_hash"], "Summary protocol")
    same(summary["replay_input_sha256"], snapshot["input_sha256"], "Summary replay input")
    if not all(value["complete"] for value in summary["policies"].values()):
        raise ValueError("Refusing final policy audit until all prespecified episodes are complete.")
    journal_path = DIRECTORY / "episodes.jsonl"
    before = file_hash(journal_path)
    episodes = [json.loads(line) for line in journal_path.read_text().splitlines()]
    same(len(episodes), 72, "Completed episode count")
    same(Counter((episode["policy"], episode["source_id"]) for episode in episodes),
         Counter({(policy, source): 1 for policy in policies for source in source_ids}), "Exact policy/source coverage")
    checked = []
    compact_keys = ["id", "tool", "width", "height", "score", "score_kind", "delta_from_original", "decision_changed", "error"]
    catalog_actions = protocol["catalog"][1:] + ["finish"]
    for episode in episodes:
        source, policy = episode["source_id"], episode["policy"]
        same(episode["protocol_hash"], protocol["protocol_hash"], "Episode protocol")
        same(episode["replay_input_sha256"], snapshot["input_sha256"], "Episode replay input")
        observations, decisions = episode["observations"], episode["decisions"]
        same(observations[0]["tool"], "baseline", "Mandatory original")
        tools = [item["tool"] for item in observations]
        same(len(tools), len(set(tools)), "No repeated detector tools")
        same([item["id"] for item in observations], [f"E{index + 1}" for index in range(len(observations))], "Sequential evidence IDs")
        baseline = lookup[source, "baseline"]["score"]
        changes = 0
        for index, item in enumerate(observations):
            row = lookup[source, item["tool"]]
            for key in ("score", "width", "height", "cache_key"):
                same(item[key], row[key], f"Observation {key} matches frozen catalog")
            same(item["score_kind"], "ai_generation", "Score meaning")
            same(item["score_origin"], "frozen_benchmark_replay", "Replay origin")
            same(item["error"], None, "Successful replay observation")
            if index:
                changed = (item["score"] > .5) != (baseline > .5)
                same(item["decision_changed"], changed, "Threshold change")
                close(item["delta_from_original"], item["score"] - baseline, "Score difference")
                changes += int(changed)
        available_count, invalid, terminal = 1, False, "budget_exhausted"
        for index, decision in enumerate(decisions):
            available = observations[:available_count]
            compact = [{key: item[key] for key in compact_keys if key in item} for item in available]
            offered = [action for action in catalog_actions if action not in {item["tool"] for item in available}]
            same(decision["evidence_ids"], [item["id"] for item in available], "Only prior evidence IDs offered")
            same(decision["observed_evidence"], compact, "Only prior observations offered")
            same(decision["offered_actions"], offered, "Remaining allowlist")
            action = decision["action"]
            if action not in offered:
                invalid = True
                terminal = "planner_failed" if decision.get("error") else "invalid_action"
                same(index, len(decisions)-1, "Invalid action terminates episode")
                break
            if policy == "local_llm":
                same(decision["model_file_sha256"], protocol["planner_files_sha256"], "Pinned planner files")
                same(decision["model_revision"], protocol["planner_revision"], "Pinned planner revision")
                weights = decision["action_weights"]
                same([item["action"] for item in weights], offered, "Action weights correspond to offered tools")
                if any(not math.isfinite(item["weight"]) or not 0 <= item["weight"] <= 1 for item in weights):
                    raise AssertionError("Invalid action weight")
                if abs(sum(item["weight"] for item in weights)-1) > 1e-6:
                    raise AssertionError("Action weights do not sum to one within float32 tolerance")
                selected_weight = next(item["weight"] for item in weights if item["action"] == action)
                if selected_weight < max(item["weight"] for item in weights) - 1e-7:
                    raise AssertionError("Chosen action is inconsistent with maximum weight beyond float32 rounding tolerance")
            if action == "finish":
                terminal = "planner_finished"
                same(index, len(decisions)-1, "Finish terminates episode")
                break
            same(observations[available_count]["tool"], action, "Chosen tool produced next observation")
            available_count += 1
        same(available_count, len(observations), "All observations explained by decisions")
        if terminal == "budget_exhausted":
            same(len(observations), protocol["budget"], "Exhausted budget consumed exactly")
        same(episode["detector_tool_calls"], len(observations), "Model-tool count")
        same(episode["valid_actions"], not invalid, "Action validity accounting")
        same(episode["budget_compliant"], len(observations) <= protocol["budget"], "Budget accounting")
        same(episode["summary"]["stop_reason"], terminal, "Stop reason")
        same(episode["reference_instability"], reference[source], "Catalog reference instability")
        same(episode["discovered_instability"], changes > 0, "Observed instability discovery")
        same(episode["summary"]["decision_changes"], changes, "Grounded summary changes")
        same(episode["summary"]["ai_tests"], len(observations), "Grounded summary AI tests")
        same(episode["summary"]["perturbation_tests"], len(observations)-1, "Grounded summary perturbation tests")
        ids = {item["id"] for item in observations}
        evidence_valid = all(set(fact["evidence_ids"]) <= ids for fact in episode["summary"]["facts"])
        same(episode["evidence_references_valid"], evidence_valid, "Evidence validity accounting")
        planner_seconds = sum(decision["runtime_seconds"] for decision in decisions)
        close(episode["planner_seconds"], planner_seconds, "Planner runtime accounting")
        if policy == "fixed":
            same([decision["action"] for decision in decisions], protocol["fixed_sequence"], "Fixed sequence")
        checked.append({"source_id": source, "policy": policy, "calls": len(observations), "changes": changes,
            "reference_instability": reference[source], "discovered": changes > 0, "valid_actions": not invalid,
            "budget_compliant": len(observations) <= 4, "evidence_valid": evidence_valid,
            "failed": terminal in {"planner_failed", "invalid_action"}, "planner_seconds": planner_seconds,
            "actions": [decision["action"] for decision in decisions]})
    policy_results = {}
    for policy in policies:
        selected = [row for row in checked if row["policy"] == policy]
        count = len(selected)
        unstable, discovered = sum(row["reference_instability"] for row in selected), sum(row["discovered"] for row in selected)
        values = {"episodes": count, "complete": count == 24, "reference_unstable_sources": unstable,
            "discovered_unstable_sources": discovered, "instability_discovery_recall": discovered / unstable if unstable else None,
            "mean_detector_tool_calls": sum(row["calls"] for row in selected) / count,
            "mean_planner_seconds": sum(row["planner_seconds"] for row in selected) / count,
            "valid_action_episodes": sum(row["valid_actions"] for row in selected),
            "failed_episodes": sum(row["failed"] for row in selected),
            "budget_compliant_episodes": sum(row["budget_compliant"] for row in selected),
            "valid_evidence_reference_episodes": sum(row["evidence_valid"] for row in selected),
            "selected_action_counts": dict(Counter("null" if action is None else action for row in selected for action in row["actions"]))}
        for key, value in values.items():
            expected = summary["policies"][policy][key]
            close(value, expected, f"{policy}/{key}") if isinstance(value, float) else same(value, expected, f"{policy}/{key}")
        policy_results[policy] = values
    same(file_hash(journal_path), before, "Episode journal stable during audit")
    output = {"status": "passed", "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_hash": protocol["protocol_hash"], "replay_input_sha256": snapshot["input_sha256"],
        "episode_journal_sha256": before, "summary_sha256": file_hash(summary_path), "audit_script_sha256": file_hash(Path(__file__)),
        "episodes": len(episodes), "sources": len(source_ids), "matched_groups": len(group_members),
        "reference_instability_is_identical_across_policies": True, "policies": policy_results,
        "checked_episodes": checked,
        "scope": "Independent reconstruction from frozen scores and raw observations; no project evaluation/planner code imported and no inference executed. Verifies accounting and evidence consistency, not policy superiority, factual ground truth, or human-rated explanation quality."}
    OUTPUT.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": output["status"], "episodes": len(episodes), "policies": policy_results}, indent=2))
    print(OUTPUT)


if __name__ == "__main__":
    main()
