"""Budgeted, observation-driven investigation with auditable tool dispatch."""
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import time
import uuid

from .pipeline import decode_image, encode, sha256, distortion
from .detectors import publish_regional, run_trufor

ACTIONS = [
    {"id": "jpeg_q85_r1", "description": "One JPEG encode at quality 85; detect resulting image."},
    {"id": "jpeg_q85_r3", "description": "Three cumulative JPEG encodes at quality 85; detect final image."},
    {"id": "resize_s0.9_r1", "description": "Resize original to 90% with LANCZOS; detect resulting image."},
    {"id": "combined_q95_s0.9_r3", "description": "Three cumulative 90% resize then quality-95 JPEG rounds; detect final image."},
    {"id": "trufor", "description": "Scan original for LOCAL MANIPULATION and reliability maps; does not identify AI-generated pixels."},
    {"id": "finish", "description": "Stop and report only measured evidence and uncertainty."},
]


def validate_agent_config(config):
    budget = config.get("budget", 4)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 2 <= budget <= 6:
        raise ValueError("Investigation budget must be an integer from 2 to 6 model-tool calls.")
    regional = config.get("allow_regional", True)
    if not isinstance(regional, bool):
        raise ValueError("allow_regional must be a boolean.")
    if "threshold" in config and config["threshold"] != .5:
        raise ValueError("The adaptive investigation uses a fixed 0.5 threshold. Remove the threshold field or set it to 0.5.")
    return {"budget": budget, "allow_regional": regional, "threshold": .5,
            "threshold_rule": "score > threshold", "planner_call_limit": budget,
            "trufor_timeout_seconds": 600}


def compact_observation(item):
    return {k: item[k] for k in ["id", "tool", "width", "height", "score", "score_kind", "delta_from_original", "decision_changed", "error"] if k in item}


def grounded_summary(observations, stop_reason):
    scored = [o for o in observations if o.get("score") is not None and o.get("score_kind") == "ai_generation"]
    original = next((o for o in scored if o["tool"] == "baseline"), None)
    derivatives = [o for o in scored if o["tool"] != "baseline"]
    facts = []
    if original:
        facts.append({"text": f"B-Free scored the normalized original {original['score']:.4f} at a fixed threshold of 0.5 (strictly greater is elevated).", "evidence_ids": [original["id"]]})
    if original and derivatives:
        flips = [o for o in derivatives if (o["score"] > .5) != (original["score"] > .5)]
        lo, hi = min(o["score"] for o in scored), max(o["score"] for o in scored)
        facts.append({"text": f"Across the original and {len(derivatives)} selected perturbation tests, scores ranged from {lo:.4f} to {hi:.4f}; {len(flips)} perturbations changed the threshold decision relative to the original.", "evidence_ids": [o["id"] for o in scored]})
        title = "Processing-sensitive evidence" if flips else "Elevated scores persist in selected tests" if original["score"] > .5 else "Low scores in selected tests"
    else:
        title = "Insufficient robustness evidence"
    for item in observations:
        if item.get("score_kind") == "local_manipulation" and item.get("score") is not None:
            facts.append({"text": f"TruFor returned a local-manipulation score of {item['score']:.4f}. Its maps address manipulation anomalies, not AI origin.", "evidence_ids": [item["id"]]})
    errors = [o["id"] for o in observations if o.get("error")]
    warnings = [
        "Detector scores are model evidence, not calibrated probabilities or proof of origin.",
        "Perturbations of one image are correlated and are not independent corroboration.",
        "The agent selects a subset of tests. Untested transformations and generators may behave differently.",
        "Low AI scores do not establish authenticity. TruFor does not localize AI generation.",
        "Planner action weights are relative selection preferences, not confidence estimates.",
    ]
    if errors:
        warnings.append("Some tools failed; missing results were not replaced with zero scores.")
    return {"title": title, "facts": facts, "warnings": warnings, "error_evidence_ids": errors, "stop_reason": stop_reason,
            "evidence_ids": [o["id"] for o in scored], "ai_tests": len(scored), "perturbation_tests": len(derivatives),
            "decision_changes": sum((o["score"] > .5) != (original["score"] > .5) for o in derivatives) if original else None}


def save_investigation(report, directory):
    temporary = directory / "investigation.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(directory / "investigation.json")
    fields = ["id", "tool", "score_kind", "score", "raw_logit", "width", "height", "mse", "psnr_db", "delta_from_original", "decision_changed", "sha256", "runtime_seconds", "error"]
    with (directory / "investigation.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["observations"])


def investigate(data, filename, config, output_root, detector, planner, *, run_id=None, progress=None, cancelled=None, regional_runner=None):
    from .benchmark import DEFAULT_CONDITIONS, render_condition

    config = validate_agent_config(config)
    original, source = decode_image(data)
    run_id = run_id or uuid.uuid4().hex
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("Invalid investigation ID.")
    directory = Path(output_root) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "source.bin").write_bytes(data)
    normalized = encode(original, "PNG")
    (directory / "original.png").write_bytes(normalized)
    started = time.perf_counter()
    report = {"schema_version": 1, "kind": "adaptive_investigation", "run_id": run_id, "status": "running",
              "image": {"name": Path(filename).name[:240], "width": original.width, "height": original.height,
                        "sha256": sha256(data), "normalized_sha256": sha256(normalized), "bytes": len(data), **source},
              "config": config, "planner": {"name": planner.name}, "observations": [], "decisions": [],
              "model_tool_calls": 0, "planner_calls": 0, "current_step": "Scoring the original image",
              "exports": {"json_url": f"/runs/{run_id}/investigation.json", "csv_url": f"/runs/{run_id}/investigation.csv"},
              "preview_url": f"/runs/{run_id}/original.png", "summary": None}

    def emit():
        report["runtime_seconds"] = time.perf_counter() - started
        save_investigation(report, directory)
        if progress:
            progress(json.loads(json.dumps(report)))

    def tool(action):
        if report["model_tool_calls"] >= config["budget"]:
            raise RuntimeError("Model-tool budget exhausted.")
        report["model_tool_calls"] += 1
        report["current_step"] = f"Running {action}"
        emit()
        item = {"id": f"E{len(report['observations'])+1}", "tool": action, "score": None, "error": None}
        tool_started = time.perf_counter()
        try:
            if action == "trufor":
                if regional_runner:
                    result = regional_runner(directory / "original.png", directory)
                else:
                    result = run_trufor(directory / "original.png", directory, os.environ["TRUFOR_REPO"], os.environ.get("TRUFOR_PYTHON", "python3"), os.environ.get("TRUFOR_DEVICE", "cpu"))
                if result.get("status") != "complete":
                    raise RuntimeError(result.get("message", "Regional tool did not return complete evidence."))
                record = publish_regional(result, directory, run_id, "agent-")
                item.update(score=float(record["score"]), score_kind="local_manipulation", detector_evidence=record)
                item.update({key: record[key] for key in ("heatmap_url", "reliability_url", "overlay_url") if key in record})
            else:
                condition = next(c for c in DEFAULT_CONDITIONS if c["name"] == action)
                current, content, fmt, operations = render_condition(original, condition)
                path = directory / (action + (".jpg" if fmt == "JPEG" else ".png"))
                path.write_bytes(content)
                mse, psnr = distortion(original, current)
                item.update(width=current.width, height=current.height, sha256=sha256(content), operations=operations,
                            mse=mse, psnr_db=psnr, preview_url=f"/runs/{run_id}/{path.name}")
                if not detector.available:
                    raise RuntimeError(detector.reason)
                result = detector.detect(path)
                item.update(score=float(result["score"]), raw_logit=result.get("raw_logit"), score_kind="ai_generation", detector_evidence=result)
                baseline = next((o for o in report["observations"] if o["tool"] == "baseline"), None)
                if baseline and baseline["score"] is not None:
                    item.update(delta_from_original=item["score"] - baseline["score"], decision_changed=(item["score"] > .5) != (baseline["score"] > .5))
            if not math.isfinite(item["score"]) or not 0 <= item["score"] <= 1:
                raise ValueError("Invalid detector score.")
            json.dumps(item, allow_nan=False)
        except Exception as exc:
            for key in ("detector_evidence", "raw_logit", "delta_from_original", "decision_changed"):
                item.pop(key, None)
            item.update(score=None, error=f"{type(exc).__name__}: {exc}")
        item["runtime_seconds"] = time.perf_counter() - tool_started
        report["observations"].append(item)
        emit()

    stop_reason = "budget_exhausted"
    emit()
    tool("baseline")  # Required measurement; explicitly not an LLM decision.
    if report["observations"][0]["error"]:
        stop_reason = "original_detector_failed"
    else:
        while report["model_tool_calls"] < config["budget"]:
            if cancelled and cancelled():
                stop_reason = "cancelled"
                break
            used = {o["tool"] for o in report["observations"]}
            actions = [a for a in ACTIONS if a["id"] not in used and (a["id"] != "trufor" or config["allow_regional"] and (regional_runner is not None or bool(os.environ.get("TRUFOR_REPO"))))]
            report["current_step"] = "Planner choosing the next step from observed evidence"
            emit()
            context = [compact_observation(o) for o in report["observations"]]
            try:
                report["planner_calls"] += 1
                choice = planner.choose(context, actions, config["budget"] - report["model_tool_calls"])
                if choice.get("action") not in {a["id"] for a in actions}:
                    raise ValueError("Planner selected a tool outside the offered allowlist.")
            except Exception as exc:
                report["planner_error"] = f"{type(exc).__name__}: {exc}"
                stop_reason = "planner_failed"
                break
            report["decisions"].append({**choice, "step": len(report["decisions"]) + 1,
                                        "evidence_ids": [o["id"] for o in report["observations"]],
                                        "observed_evidence": context, "offered_actions": [a["id"] for a in actions]})
            emit()
            if cancelled and cancelled():
                stop_reason = "cancelled"
                break
            if choice["action"] == "finish":
                stop_reason = "planner_finished"
                break
            tool(choice["action"])
    report["status"] = "cancelled" if stop_reason == "cancelled" else "error" if stop_reason in {"planner_failed", "original_detector_failed"} else "complete"
    report["current_step"] = "Investigation complete" if report["status"] == "complete" else f"Investigation stopped: {stop_reason.replace('_', ' ')}"
    report["summary"] = grounded_summary(report["observations"], stop_reason)
    emit()
    return report
