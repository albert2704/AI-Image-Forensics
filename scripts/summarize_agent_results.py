"""Write an evidence-backed narrative of the completed frozen policy replay."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "output/agent-evaluation"
NAMES = {"fixed": "Fixed workflow", "rule": "Rule baseline", "local_llm": "Local Qwen"}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main():
    protocol = json.loads((DIRECTORY / "protocol.json").read_text())
    summary = json.loads((DIRECTORY / "summary.json").read_text())
    episodes = [json.loads(line) for line in (DIRECTORY / "episodes.jsonl").read_text().splitlines()]
    expected_hash = canonical_hash({k: v for k, v in protocol.items() if k != "protocol_hash"})
    if protocol["protocol_hash"] != expected_hash or summary["protocol_hash"] != expected_hash:
        raise ValueError("Protocol identity mismatch.")
    expected = {(policy, source) for policy in protocol["policies"] for source in protocol["source_ids"]}
    observed = {(episode["policy"], episode["source_id"]) for episode in episodes}
    if observed != expected or len(episodes) != len(expected):
        raise ValueError("The report requires every prespecified policy/source episode exactly once.")
    if any(episode["protocol_hash"] != expected_hash or episode["replay_input_sha256"] != summary["replay_input_sha256"] for episode in episodes):
        raise ValueError("Episode provenance mismatch.")
    if not all(row["complete"] for row in summary["policies"].values()):
        raise ValueError("Policy summary is incomplete.")

    lines = ["# Measured agent-policy results", "", "Completed 18 October 2026.", "",
        "This is a **24-source, three-policy descriptive replay pilot**: three matched real/generated test groups per generator, selected by SHA-256 ranking before policy scoring. Each policy starts with the original B-Free observation and has a four-call detector-tool budget. The same frozen detector observations are replayed; Qwen's decisions are newly executed.", "",
        "The reference event is a decision change at `score > 0.5` in any of the four available processing branches. Discovery recall measures how often a policy finds that event. It is not authenticity accuracy, and missing a change is not evidence that an image is robust under arbitrary processing.", "",
        "| Policy | Episodes | Mean detector calls | Reference changes found | Discovery recall | Failed episodes |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for policy, name in NAMES.items():
        row = summary["policies"][policy]
        selected = [e for e in episodes if e["policy"] == policy]
        if row["episodes"] != len(selected) or row["discovered_unstable_sources"] != sum(e["discovered_instability"] for e in selected):
            raise ValueError("Summary counts disagree with episodes.")
        recall = row["instability_discovery_recall"]
        lines.append(f"| {name} | {row['episodes']} | {row['mean_detector_tool_calls']:.2f} | {row['discovered_unstable_sources']}/{row['reference_unstable_sources']} | {'Not estimable' if recall is None else f'{100*recall:.1f}%'} | {row['failed_episodes']} |")
    lines.extend(["", "The fixed sequence is original → JPEG Q85 once → resize 90% once → resize/Q95 three times. The rule and Qwen policies can also choose JPEG Q85 three times or finish. All policies have the same budget and observation catalog; TruFor is disabled because the replay benchmark has no regional observations.", "", "## Validity and tool selection", ""])
    for policy, name in NAMES.items():
        row = summary["policies"][policy]
        selected = [e for e in episodes if e["policy"] == policy]
        actions = Counter(d["action"] or "failed choice" for e in selected for d in e["decisions"])
        stops = Counter(e["summary"]["stop_reason"] for e in selected)
        missed = [e["source_id"] for e in selected if e["reference_instability"] and not e["discovered_instability"]]
        lines.extend([f"### {name}", "",
            f"Valid-action episodes: {row['valid_action_episodes']}/{row['episodes']}; budget-compliant: {row['budget_compliant_episodes']}/{row['episodes']}; structurally valid evidence references: {row['valid_evidence_reference_episodes']}/{row['episodes']}.", "",
            "Selected actions: " + "; ".join(f"`{key}` × {count}" for key, count in sorted(actions.items())) + ".", "",
            "Stop reasons: " + "; ".join(f"`{key}` × {count}" for key, count in sorted(stops.items())) + ".", "",
            "Missed reference-instability source IDs: " + (", ".join(f"`{source}`" for source in missed) if missed else "none") + ".", ""])
    qwen = summary["policies"]["local_llm"]
    fixed, rule = (summary["policies"][key] for key in ["fixed", "rule"])
    qwen_sequences = {tuple(o["tool"] for o in e["observations"]) for e in episodes if e["policy"] == "local_llm"}
    lines.extend(["## Timing and interpretation", "",
        f"Only {qwen['reference_unstable_sources']} of 24 sources had reference-catalog instability. The 100% discovery recall in this completed pilot therefore represents one found event, not broad evidence of policy reliability. Qwen used {qwen['mean_detector_tool_calls']:.2f} mean calls, the fixed workflow {fixed['mean_detector_tool_calls']:.2f}, and the rule policy {rule['mean_detector_tool_calls']:.2f}. There was no observed LLM advantage in discoveries or call cost.", "",
        f"Qwen produced {len(qwen_sequences)} distinct executed tool sequence(s) across the 24 sources. Its observation-driven architecture did not yield varied test selection within this pilot; the live integration demo did stop earlier. The frozen policy was not tuned after these results.", "",
        f"Mean measured Qwen planner time was {qwen['mean_planner_seconds']:.3f} seconds per episode, including first-use model loading in the first episode. Detector runtimes are historical values attached to replay records. Neither this mean nor replay wall time is an end-to-end application latency estimate.", "",
        "This finite catalog and small sample do not support an agent-superiority claim. Valid actions are enforced by constrained token selection and dispatch; structural evidence-reference checks do not assess whether explanations are useful to people. Action ordering is fixed, possible positional bias is unmeasured, and the planner sees numeric evidence rather than image content. Failed episodes remain in the planned denominator.", "",
        "The local Qwen model uses pinned official weights in float32, with no rule fallback. The application separately demonstrated a real end-to-end investigation on an upstream integration image: original 0.988232, JPEG Q85 ×3 0.793440, resize 90% 0.271888, then finish. It used three model-tool calls in 27.6 seconds including planner loading; this one example is illustrative.", "",
        "## Reproduction and evidence", "",
        f"Protocol SHA-256: `{expected_hash}`.", "",
        f"Replay-input SHA-256: `{summary['replay_input_sha256']}`.", "",
        "- [Frozen protocol](../output/agent-evaluation/protocol.json)",
        "- [Exact replay observations](../output/agent-evaluation/replay-inputs.json)",
        "- [Complete episode journal](../output/agent-evaluation/episodes.jsonl)",
        "- [Machine-readable summary](../output/agent-evaluation/summary.json)",
        "- [Agent design](AGENT_DESIGN.md)", "",
        "Rebuild this narrative with `.venv/bin/python scripts/summarize_agent_results.py`. Replaying completed episodes resumes their journal rather than making new model decisions; use a separately frozen study for a new evaluation.", ""])
    output = ROOT / "docs/AGENT_RESULTS.md"
    output.write_text("\n".join(lines))
    print(output)


if __name__ == "__main__":
    main()
