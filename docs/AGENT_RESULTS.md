# Measured agent-policy results

Completed 18 October 2026.

This is a **24-source, three-policy descriptive replay pilot**: three matched real/generated test groups per generator, selected by SHA-256 ranking before policy scoring. Each policy starts with the original B-Free observation and has a four-call detector-tool budget. The same frozen detector observations are replayed; Qwen's decisions are newly executed.

The reference event is a decision change at `score > 0.5` in any of the four available processing branches. Discovery recall measures how often a policy finds that event. It is not authenticity accuracy, and missing a change is not evidence that an image is robust under arbitrary processing.

| Policy | Episodes | Mean detector calls | Reference changes found | Discovery recall | Failed episodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed workflow | 24 | 4.00 | 1/1 | 100.0% | 0 |
| Rule baseline | 24 | 2.54 | 1/1 | 100.0% | 0 |
| Local Qwen | 24 | 4.00 | 1/1 | 100.0% | 0 |

The fixed sequence is original → JPEG Q85 once → resize 90% once → resize/Q95 three times. The rule and Qwen policies can also choose JPEG Q85 three times or finish. All policies have the same budget and observation catalog; TruFor is disabled because the replay benchmark has no regional observations.

## Validity and tool selection

### Fixed workflow

Valid-action episodes: 24/24; budget-compliant: 24/24; structurally valid evidence references: 24/24.

Selected actions: `combined_q95_s0.9_r3` × 24; `jpeg_q85_r1` × 24; `resize_s0.9_r1` × 24.

Stop reasons: `budget_exhausted` × 24.

Missed reference-instability source IDs: none.

### Rule baseline

Valid-action episodes: 24/24; budget-compliant: 24/24; structurally valid evidence references: 24/24.

Selected actions: `combined_q95_s0.9_r3` × 12; `finish` × 23; `jpeg_q85_r1` × 24; `resize_s0.9_r1` × 1.

Stop reasons: `budget_exhausted` × 1; `planner_finished` × 23.

Missed reference-instability source IDs: none.

### Local Qwen

Valid-action episodes: 24/24; budget-compliant: 24/24; structurally valid evidence references: 24/24.

Selected actions: `combined_q95_s0.9_r3` × 24; `jpeg_q85_r3` × 24; `resize_s0.9_r1` × 24.

Stop reasons: `budget_exhausted` × 24.

Missed reference-instability source IDs: none.

## Timing and interpretation

Only 1 of 24 sources had reference-catalog instability. The 100% discovery recall in this completed pilot therefore represents one found event, not broad evidence of policy reliability. Qwen used 4.00 mean calls, the fixed workflow 4.00, and the rule policy 2.54. There was no observed LLM advantage in discoveries or call cost.

Qwen produced 1 distinct executed tool sequence(s) across the 24 sources. Its observation-driven architecture did not yield varied test selection within this pilot; the live integration demo did stop earlier. The frozen policy was not tuned after these results.

Mean measured Qwen planner time was 2.574 seconds per episode, including first-use model loading in the first episode. Detector runtimes are historical values attached to replay records. Neither this mean nor replay wall time is an end-to-end application latency estimate.

This finite catalog and small sample do not support an agent-superiority claim. Valid actions are enforced by constrained token selection and dispatch; structural evidence-reference checks do not assess whether explanations are useful to people. Action ordering is fixed, possible positional bias is unmeasured, and the planner sees numeric evidence rather than image content. Failed episodes remain in the planned denominator.

The local Qwen model uses pinned official weights in float32, with no rule fallback. The application separately demonstrated a real end-to-end investigation on an upstream integration image: original 0.988232, JPEG Q85 ×3 0.793440, resize 90% 0.271888, then finish. It used three model-tool calls in 27.6 seconds including planner loading; this one example is illustrative.

## Reproduction and evidence

Protocol SHA-256: `b34b11babb166808d5ddfdb45b14917ce6b11792c208fb73a8d91e1aa519d6c3`.

Replay-input SHA-256: `de473ccc0c8321915487422a9db8a43dcb2ad27e1fe1e6f0436b2b8be83eac5a`.

- [Frozen protocol](../output/agent-evaluation/protocol.json)
- [Exact replay observations](../output/agent-evaluation/replay-inputs.json)
- [Complete episode journal](../output/agent-evaluation/episodes.jsonl)
- [Machine-readable summary](../output/agent-evaluation/summary.json)
- [Agent design](AGENT_DESIGN.md)

Rebuild this narrative with `.venv/bin/python scripts/summarize_agent_results.py`. Replaying completed episodes resumes their journal rather than making new model decisions; use a separately frozen study for a new evaluation.
