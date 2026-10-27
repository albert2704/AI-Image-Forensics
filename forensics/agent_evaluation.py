"""Prespecified, score-replay evaluation of bounded tool-selection policies.

Replay isolates policy behavior from redundant neural inference. It is not an
end-to-end latency measurement or a claim of improved authenticity accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

from .agent import ACTIONS, compact_observation, grounded_summary
from .benchmark import load_protocol, _file_hash, _digest
from .planner import LocalPlanner, RulePlanner, MODEL_ID, MODEL_REVISION, MODEL_FILES_SHA256

CATALOG = ["baseline", "jpeg_q85_r1", "jpeg_q85_r3", "resize_s0.9_r1", "combined_q95_s0.9_r3"]
FIXED = ["jpeg_q85_r1", "resize_s0.9_r1", "combined_q95_s0.9_r3"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def code_hashes():
    return {name: _file_hash(Path(__file__).with_name(name)) for name in ["agent.py", "planner.py", "agent_evaluation.py"]}


def freeze(study_path, output):
    study = load_protocol(study_path)
    grouped = defaultdict(list)
    for source in study["sources"]:
        if source["split"] == "test":
            grouped[source["group_id"]].append(source)
    strata = defaultdict(list)
    for group, members in grouped.items():
        generated = [m for m in members if m["label"] == 1]
        if len(members) != 2 or len(generated) != 1:
            raise ValueError("Agent pilot expects one real and one generated source per test group.")
        strata[generated[0]["generator"]].append(group)
    selected = []
    for generator, groups in sorted(strata.items()):
        ordered = sorted(groups, key=lambda g: hashlib.sha256(f"agent-pilot-20261018:{g}".encode()).hexdigest())
        for group in ordered[:3]:
            selected.extend(m["source_id"] for m in sorted(grouped[group], key=lambda m: m["source_id"]))
    protocol = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "study_protocol_path": str(Path(study_path).resolve()), "study_protocol_hash": study["protocol_hash"],
                "source_ids": selected, "selection": "Three SHA256-ranked matched test groups per generator, before replay or policy scoring.",
                "budget": 4, "allow_regional": False, "catalog": CATALOG, "fixed_sequence": FIXED,
                "threshold": .5, "threshold_rule": "score > threshold", "policies": ["fixed", "rule", "local_llm"],
                "planner_model": MODEL_ID, "planner_revision": MODEL_REVISION, "planner_files_sha256": MODEL_FILES_SHA256, "code_sha256": code_hashes(),
                "primary_policy_measure": "Fraction of sources with a reference-catalog threshold change that the policy discovers within four model-tool calls.",
                "reference": "All four available perturbations vs the original; not ground-truth image authenticity.",
                "secondary_measures": ["mean detector-tool calls", "budget compliance", "valid action selection", "evidence reference validity", "planner wall time"],
                "design_limits": ["24-source descriptive pilot; no inferential superiority claim.", "TruFor is disabled for matched replay because no regional benchmark results exist.", "Detector scores and per-call inference times are replayed; only planner time is newly measured.", "Action order is fixed; potential language-model positional bias is not assessed.", "Evidence reference validity is a structural check, not human-rated explanatory quality."]}
    protocol["protocol_hash"] = digest(protocol)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(protocol, stream, indent=2)
    return protocol


def load(path):
    protocol = json.loads(Path(path).read_text())
    raw = {k: v for k, v in protocol.items() if k != "protocol_hash"}
    if digest(raw) != protocol["protocol_hash"] or protocol["code_sha256"] != code_hashes():
        raise ValueError("Agent protocol or policy implementation changed after freeze.")
    study = load_protocol(protocol["study_protocol_path"])
    if study["protocol_hash"] != protocol["study_protocol_hash"]:
        raise ValueError("Detector study changed after agent protocol freeze.")
    return protocol


def replay_source(source, rows, planner, policy, budget):
    observations, decisions = [], []
    calls = 0
    started = time.perf_counter()

    def observe(action):
        nonlocal calls
        row = rows[action]
        item = {"id": f"E{len(observations)+1}", "tool": action, "score": row["score"],
                "score_kind": "ai_generation", "width": row["width"], "height": row["height"], "error": None,
                "score_origin": "frozen_benchmark_replay", "cache_key": row["cache_key"],
                "recorded_inference_seconds": row["prediction"].get("runtime_seconds")}
        if observations:
            item.update(delta_from_original=item["score"] - observations[0]["score"], decision_changed=(item["score"] > .5) != (observations[0]["score"] > .5))
        observations.append(item)
        calls += 1

    observe("baseline")
    stop = "budget_exhausted"
    valid = True
    while calls < budget:
        used = {o["tool"] for o in observations}
        actions = [a for a in ACTIONS if a["id"] != "trufor" and a["id"] not in used]
        context = [compact_observation(o) for o in observations]
        decision_started = time.perf_counter()
        try:
            if policy == "fixed":
                choice = {"action": FIXED[calls-1], "policy": "fixed", "runtime_seconds": 0.0}
            else:
                choice = planner.choose(context, actions, budget - calls)
        except Exception as exc:
            choice = {"action": None, "policy": policy, "error": f"{type(exc).__name__}: {exc}", "runtime_seconds": time.perf_counter() - decision_started}
        decisions.append({**choice, "evidence_ids": [o["id"] for o in observations], "observed_evidence": context, "offered_actions": [a["id"] for a in actions]})
        if choice["action"] not in {a["id"] for a in actions}:
            valid, stop = False, "planner_failed" if choice.get("error") else "invalid_action"
            break
        if choice["action"] == "finish":
            stop = "planner_finished"
            break
        observe(choice["action"])
    summary = grounded_summary(observations, stop)
    ids = {o["id"] for o in observations}
    known = any((rows[c]["score"] > .5) != (rows["baseline"]["score"] > .5) for c in CATALOG[1:])
    discovered = any(o.get("decision_changed", False) for o in observations)
    return {"source_id": source, "policy": policy, "detector_tool_calls": calls, "decisions": decisions,
            "observations": observations, "summary": summary, "reference_instability": known, "discovered_instability": discovered,
            "valid_actions": valid, "budget_compliant": calls <= budget,
            "evidence_references_valid": all(set(f["evidence_ids"]) <= ids for f in summary["facts"]),
            "planner_seconds": sum(d.get("runtime_seconds", 0) for d in decisions),
            "replayed_detector_seconds": sum(o["recorded_inference_seconds"] or 0 for o in observations),
            "replay_wall_seconds": time.perf_counter() - started}


def validate_replay_rows(raw_rows, study, source_ids):
    sources = {s["source_id"]: s for s in study["sources"]}
    model_hash = _digest(study["bfree_fingerprint"])
    rows = defaultdict(dict)
    for row in raw_rows:
        source_id, condition = row["source_id"], row["condition"]
        source = sources.get(source_id)
        if source is None or row["protocol_hash"] != study["protocol_hash"] or row["model_fingerprint_sha256"] != model_hash or row["source_sha256"] != source["sha256"]:
            raise ValueError("Replay prediction provenance mismatch.")
        if condition in rows[source_id]:
            raise ValueError("Duplicate replay source/condition row.")
        if isinstance(row["score"], bool) or not isinstance(row["score"], (int, float)) or not math.isfinite(row["score"]) or not 0 <= row["score"] <= 1:
            raise ValueError("Invalid replay score.")
        if row.get("detector_id") != "bfree" or row["prediction"].get("score") != row["score"]:
            raise ValueError("Replay row and detector evidence disagree.")
        rows[source_id][condition] = row
    for source_id in source_ids:
        if not set(CATALOG) <= set(rows[source_id]):
            raise ValueError(f"Required replay observations are incomplete for {source_id}.")
    return rows


def run(protocol_path, policies=None):
    protocol = load(protocol_path)
    policies = policies or protocol["policies"]
    if not set(policies) <= set(protocol["policies"]):
        raise ValueError("Unknown evaluation policy.")
    study = load_protocol(protocol["study_protocol_path"])
    input_path = Path(protocol["study_protocol_path"]).parent / "results" / "bfree" / "predictions.jsonl"
    rows = validate_replay_rows([json.loads(line) for line in input_path.read_text().splitlines()], study, protocol["source_ids"])
    directory = Path(protocol_path).parent
    journal = directory / "episodes.jsonl"
    snapshot = {"protocol_hash": protocol["protocol_hash"], "rows": [rows[s][c] for s in protocol["source_ids"] for c in CATALOG]}
    input_hash = digest(snapshot)
    snapshot["input_sha256"] = input_hash
    snapshot_path = directory / "replay-inputs.json"
    if snapshot_path.exists():
        if json.loads(snapshot_path.read_text()) != snapshot:
            raise ValueError("Replay input records changed; old episodes cannot be resumed against new evidence.")
    elif journal.exists():
        raise ValueError("Existing episodes have no frozen replay-input snapshot.")
    else:
        with snapshot_path.open("x", encoding="utf-8") as stream:
            json.dump(snapshot, stream, indent=2, allow_nan=False)
    episodes = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
    if any(e["protocol_hash"] != protocol["protocol_hash"] or e.get("replay_input_sha256") != input_hash or e["source_id"] not in protocol["source_ids"] or e["policy"] not in protocol["policies"] for e in episodes):
        raise ValueError("Episode journal belongs to another protocol.")
    done = {(e["policy"], e["source_id"]) for e in episodes}
    if len(done) != len(episodes):
        raise ValueError("Duplicate policy/source episodes in journal.")
    planner = LocalPlanner()
    for policy in policies:
        selected_planner = planner if policy == "local_llm" else RulePlanner()
        for source in protocol["source_ids"]:
            if (policy, source) in done:
                continue
            result = replay_source(source, rows[source], selected_planner, policy, protocol["budget"])
            result["protocol_hash"] = protocol["protocol_hash"]
            result["replay_input_sha256"] = input_hash
            with journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, allow_nan=False) + "\n")
                stream.flush()
            episodes.append(result)
            print(f"{policy}: {source}, calls={result['detector_tool_calls']}, instability={result['discovered_instability']}", flush=True)
    summary = {"protocol_hash": protocol["protocol_hash"], "replay_input_sha256": input_hash, "selected_sources": len(protocol["source_ids"]),
               "design_limits": protocol["design_limits"], "policies": {}}
    for policy in protocol["policies"]:
        selected = [e for e in episodes if e["policy"] == policy]
        n = len(selected)
        unstable = sum(e["reference_instability"] for e in selected)
        discovered = sum(e["discovered_instability"] for e in selected)
        summary["policies"][policy] = {"episodes": n, "complete": n == len(protocol["source_ids"]),
            "reference_unstable_sources": unstable, "discovered_unstable_sources": discovered,
            "instability_discovery_recall": discovered / unstable if unstable else None,
            "mean_detector_tool_calls": sum(e["detector_tool_calls"] for e in selected) / n if n else None,
            "mean_planner_seconds": sum(e["planner_seconds"] for e in selected) / n if n else None,
            "valid_action_episodes": sum(e["valid_actions"] for e in selected),
            "failed_episodes": sum(e["summary"]["stop_reason"] in {"planner_failed", "invalid_action"} for e in selected),
            "budget_compliant_episodes": sum(e["budget_compliant"] for e in selected),
            "valid_evidence_reference_episodes": sum(e["evidence_references_valid"] for e in selected),
            "selected_action_counts": dict(Counter(d["action"] for e in selected for d in e["decisions"]))}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("freeze")
    command.add_argument("study", type=Path)
    command.add_argument("--output", type=Path, required=True)
    command = sub.add_parser("run")
    command.add_argument("protocol", type=Path)
    command.add_argument("--policies", nargs="+", choices=["fixed", "rule", "local_llm"])
    args = parser.parse_args()
    print(json.dumps(freeze(args.study, args.output) if args.command == "freeze" else run(args.protocol, args.policies), indent=2))


if __name__ == "__main__":
    main()
