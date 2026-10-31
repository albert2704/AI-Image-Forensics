"""Frozen, resumable source/group aware research benchmark.

Freeze a protocol before scoring, then run either the configured B-Free model or
the train-only frequency baseline. Successful predictions and failures are
append-only journals; CSV and summary JSON are derived views, never fitted data.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, __version__ as pillow_version

from . import pipeline
from .evaluation import evaluate_rows


DEFAULT_CONDITIONS = [
    {"name": "baseline", "operation": "combined", "quality": 95, "scale": .9, "rounds": 0, "mode": "cumulative", "order": "resize-jpeg"},
    *[{"name": f"jpeg_q85_r{r}", "operation": "jpeg", "quality": 85, "scale": 1., "rounds": r, "mode": "cumulative", "order": "resize-jpeg"} for r in (1, 3)],
    *[{"name": f"resize_s0.9_r{r}", "operation": "resize", "quality": 95, "scale": .9, "rounds": r, "mode": "cumulative", "order": "resize-jpeg"} for r in (1, 3)],
    *[{"name": f"combined_q95_s0.9_r{r}", "operation": "combined", "quality": 95, "scale": .9, "rounds": r, "mode": "cumulative", "order": "resize-jpeg"} for r in (1, 3)],
    {"name": "reverse_q95_s0.9_r3", "operation": "combined", "quality": 95, "scale": .9, "rounds": 3, "mode": "cumulative", "order": "jpeg-resize"},
    {"name": "independent_q95_s0.9_r3", "operation": "combined", "quality": 95, "scale": .9, "rounds": 3, "mode": "independent", "order": "resize-jpeg"},
]
SPLITS = ("train", "validation", "test")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_image_hash(image: Image.Image) -> str:
    """Identity of normalized RGB pixels and dimensions, independent of container."""
    image = image.convert("RGB")
    digest = hashlib.sha256(_json_bytes({"mode": "RGB", "size": list(image.size)}))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _code_fingerprint():
    root = Path(__file__).resolve().parent
    return {"files": {name: _file_hash(root / name) for name in ("pipeline.py", "evaluation.py", "benchmark.py", "frequency_baseline.py")},
            "python": platform.python_version(), "pillow": pillow_version, "numpy": np.__version__}


def detector_fingerprint(detector):
    """Hash configured model/preprocessing without triggering neural inference."""
    explicit = getattr(detector, "fingerprint", None)
    if explicit is not None:
        fingerprint = copy.deepcopy(explicit() if callable(explicit) else explicit)
    elif hasattr(detector, "_checkpoint") and hasattr(detector, "code_dir"):
        code = Path(detector.code_dir)
        source_files = sorted([*code.joinpath("networks").rglob("*.py"), *code.joinpath("utils").rglob("*.py")])
        source_hashes = {str(path.relative_to(code)): _file_hash(path) for path in source_files}
        versions = {}
        for name in ("torch", "torchvision", "timm", "PyYAML"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "unavailable"
        fingerprint = {"model_type": "bfree", "name": detector.name,
                       "checkpoint_sha256": _file_hash(detector._checkpoint),
                       "preprocess_sha256": _digest({"config": detector._config, "upstream_code": source_hashes,
                                                     "adapter": _file_hash(Path(__file__).with_name("detectors.py"))}),
                       "model_revision": detector.model_revision, "device": detector.device, "versions": versions}
    else:
        raise ValueError("Detector must expose a reproducible fingerprint, including checkpoint_sha256 and preprocess_sha256.")
    if not isinstance(fingerprint, dict) or not all(isinstance(fingerprint.get(key), str) and fingerprint[key] for key in ("checkpoint_sha256", "preprocess_sha256")):
        raise ValueError("Invalid detector fingerprint.")
    _json_bytes(fingerprint)
    return fingerprint


def _validate_conditions(conditions):
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("At least one condition is required.")
    names = set()
    result = []
    for raw in conditions:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", raw["name"]):
            raise ValueError("Condition names must contain only letters, numbers, underscore, dot or hyphen.")
        if raw["name"] in names:
            raise ValueError("Condition names must be unique.")
        names.add(raw["name"])
        if raw["name"] == "baseline":
            if raw.get("rounds") != 0:
                raise ValueError("Baseline must use zero transformation rounds.")
            validated = pipeline.validate_config({**raw, "rounds": 1})
            validated["rounds"] = 0
        else:
            validated = pipeline.validate_config(raw)
        validated.pop("threshold", None)
        result.append({"name": raw["name"], **validated})
    if "baseline" not in names:
        raise ValueError("Conditions must include baseline.")
    return result


def render_condition(original: Image.Image, condition: dict):
    """Return final pixels, encoded artifact, format and complete operation history.

    Both modes have the same target dimensions. Independent mode applies one
    pass from the original at the final target; cumulative mode decodes every
    intermediate encoding through pipeline.transform.
    """
    name = condition.get("name")
    if name == "baseline":
        if condition.get("rounds") != 0:
            raise ValueError("Baseline must use zero rounds.")
        image = original.convert("RGB")
        return image, pipeline.encode(image, "PNG"), "PNG", []
    config = pipeline.validate_config(condition)
    current = original.convert("RGB")
    history = []
    rounds = range(1, config["rounds"] + 1) if config["mode"] == "cumulative" else (config["rounds"],)
    for round_index in rounds:
        factor = config["scale"] ** round_index if config["operation"] != "jpeg" else 1.
        target = (max(1, round(original.width * factor)), max(1, round(original.height * factor)))
        parent = canonical_image_hash(current)
        current, content, fmt, operations = pipeline.transform(current, target, config)
        history.extend({**step, "round": round_index, "parent_pixel_sha256": parent} for step in operations)
    return current, content, fmt, history


def _manifest_records(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    required = {"source_id", "path", "label", "generator", "group_id", "split", "sha256", "source_url"}
    with manifest_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = [x.strip() for x in reader.fieldnames or []]
        if not required.issubset(headers) or len(headers) != len(set(headers)) or any(not x for x in headers):
            raise ValueError("Manifest needs unique source_id,path,label,generator,group_id,split,sha256,source_url columns.")
        reader.fieldnames = headers
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("Manifest contains no images.")
    records, source_ids, pixel_hashes, groups = [], set(), set(), {}
    for index, raw in enumerate(raw_rows, start=2):
        if None in raw:
            raise ValueError(f"Manifest line {index} has extra values.")
        row = {key: value.strip() if isinstance(value, str) else "" for key, value in raw.items()}
        if any(not row.get(key) for key in required) or row["label"] not in {"0", "1"} or row["split"] not in SPLITS:
            raise ValueError(f"Manifest line {index} contains blank metadata, invalid label or split.")
        if re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None:
            raise ValueError(f"Manifest line {index} needs a lowercase SHA-256 checksum.")
        if row["source_id"] in source_ids:
            raise ValueError("Duplicate source_id after trimming whitespace.")
        source_ids.add(row["source_id"])
        if row["group_id"] in groups and groups[row["group_id"]] != row["split"]:
            raise ValueError("A group_id crosses dataset splits.")
        groups[row["group_id"]] = row["split"]
        path = (manifest_path.parent / row["path"]).resolve(strict=True)
        data = path.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if row.get("sha256") and row["sha256"] != actual_hash:
            raise ValueError(f"Source checksum does not match manifest: {row['source_id']}")
        image, info = pipeline.decode_image(data)
        pixel_hash = canonical_image_hash(image)
        if pixel_hash in pixel_hashes:
            raise ValueError("Duplicate normalized image pixels across source IDs.")
        pixel_hashes.add(pixel_hash)
        records.append({**row, "path": str(path), "label": int(row["label"]), "sha256": actual_hash,
                        "pixel_sha256": pixel_hash, "width": image.width, "height": image.height,
                        "bytes": len(data), "normalization": info})
    for split in SPLITS:
        if {row["label"] for row in records if row["split"] == split} != {0, 1}:
            raise ValueError(f"Split {split} needs both label classes before the protocol can be frozen.")
    return sorted(records, key=lambda row: row["source_id"])


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def freeze_protocol(manifest_path, run_dir, config=None):
    """Freeze data, conditions, model identity and analysis before any scoring."""
    from .frequency_baseline import FEATURE_SPEC, TRAINING_SPEC
    config = copy.deepcopy(config or {})
    unknown = set(config) - {"conditions", "threshold", "seed", "bootstrap_samples", "bfree_fingerprint", "study_name"}
    if unknown:
        raise ValueError(f"Unknown protocol settings: {sorted(unknown)}")
    run_dir = Path(run_dir).resolve()
    path = run_dir / "protocol.json"
    if path.exists():
        raise FileExistsError("A protocol is already frozen here; reuse it or choose a new run directory.")
    threshold = config.get("threshold", .5)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be finite and in [0, 1].")
    for key, default in (("seed", 2026), ("bootstrap_samples", 2000)):
        value = config.setdefault(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer.")
    records = _manifest_records(manifest_path)
    protocol = {"schema_version": 1, "created_at_utc": _now(),
                "study_name": config.get("study_name", "Repeated JPEG and resizing benchmark"),
                "manifest_path": str(Path(manifest_path).resolve()), "manifest_sha256": _file_hash(manifest_path),
                "sources": records, "conditions": _validate_conditions(config.get("conditions", DEFAULT_CONDITIONS)),
                "threshold": float(threshold), "threshold_rule": "score > threshold",
                "seed": config["seed"], "bootstrap_samples": config["bootstrap_samples"],
                "analysis_unit": "source_id; confidence intervals resample complete group_id clusters",
                "bfree_fingerprint": config.get("bfree_fingerprint"),
                "frequency": {"feature_spec": FEATURE_SPEC, "training_spec": TRAINING_SPEC, "fit_split": "train", "threshold_selection": "fixed, no validation tuning"},
                "code_fingerprint": _code_fingerprint()}
    protocol["protocol_hash"] = _digest(protocol)
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(protocol, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return protocol


def load_protocol(path, verify_sources=False):
    path = Path(path)
    protocol = json.loads(path.read_text(encoding="utf-8"))
    stored_hash = protocol.get("protocol_hash")
    if stored_hash != _digest({key: value for key, value in protocol.items() if key != "protocol_hash"}):
        raise ValueError("Frozen protocol was altered or corrupted.")
    if protocol["code_fingerprint"] != _code_fingerprint():
        raise ValueError("Code or runtime versions changed since protocol freeze; use a new protocol.")
    if _file_hash(protocol["manifest_path"]) != protocol["manifest_sha256"]:
        raise ValueError("Manifest changed after protocol freeze.")
    if verify_sources:
        for source in protocol["sources"]:
            if _file_hash(source["path"]) != source["sha256"]:
                raise ValueError(f"Source changed after protocol freeze: {source['source_id']}")
    return protocol


@contextmanager
def _run_lock(run_dir):
    """Hold an exclusive lock on a study directory on POSIX and Windows hosts."""
    with (Path(run_dir) / ".run.lock").open("a") as handle:
        release = _acquire_file_lock(handle)
        try:
            yield
        finally:
            release()


def _acquire_file_lock(handle):
    """Lock one byte of an open file and return its release callable.

    POSIX hosts use flock; Windows uses msvcrt's byte-range lock. Both are
    advisory and process-scoped, which is what stops two writers appending to
    the same journal.
    """
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another benchmark writer is running in this directory.") from exc
        return lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    try:
        import msvcrt
    except ImportError as exc:  # pragma: no cover - no known host lacks both
        raise RuntimeError("This platform cannot lock a study directory.") from exc
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        raise RuntimeError("Another benchmark writer is running in this directory.") from exc

    def release():
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    return release


def _read_journal(path):
    if not Path(path).exists():
        return []
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"Journal {path} line {number} is incomplete or corrupt; preserve it before repair.") from exc
            rows.append(row)
    return rows


def _append(path, row):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(_json_bytes(row).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _valid_prediction(prediction):
    if not isinstance(prediction, dict):
        raise ValueError("Detector returned no prediction mapping.")
    score = prediction.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float, np.integer, np.floating)) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Detector score must be a finite number in [0, 1].")
    result = {**prediction, "score": float(score)}
    if result.get("raw_logit") is not None:
        result["raw_logit"] = float(result["raw_logit"])
        if not math.isfinite(result["raw_logit"]):
            raise ValueError("Detector raw_logit must be finite.")
    _json_bytes(result)
    return result


def _check_detector(protocol, detector_id, fingerprint):
    if detector_id == "bfree":
        if protocol.get("bfree_fingerprint") != fingerprint:
            raise ValueError("B-Free fingerprint differs from the frozen protocol.")
    elif detector_id == "frequency":
        expected_ids = sorted(row["source_id"] for row in protocol["sources"] if row["split"] == "train")
        if fingerprint.get("protocol_hash") != protocol["protocol_hash"] or sorted(fingerprint.get("training_source_ids", [])) != expected_ids:
            raise ValueError("Frequency model was not fitted on this protocol's exact train split.")
    else:
        raise ValueError("detector_id must be bfree or frequency.")


def _write_predictions_csv(rows, path):
    fields = ["source_id", "label", "generator", "group_id", "split", "condition", "score", "raw_logit", "protocol_hash", "pixel_sha256", "cache_key"]
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["split"], row["source_id"], row["condition"])))


def grouped_paired_interval(rows, condition, threshold=.5, samples=2000, seed=2026):
    """Percentile CI retaining every paired source in each sampled group."""
    baseline = {row["source_id"]: row for row in rows if row["condition"] == "baseline"}
    variant = {row["source_id"]: row for row in rows if row["condition"] == condition}
    shared = sorted(baseline.keys() & variant.keys())
    clusters = defaultdict(list)
    for source in shared:
        before, after = baseline[source], variant[source]
        if before["group_id"] != after["group_id"] or before["label"] != after["label"]:
            raise ValueError("Paired source metadata changed across conditions.")
        label = int(before["label"])
        delta = int((after["score"] > threshold) == label) - int((before["score"] > threshold) == label)
        clusters[before["group_id"]].append((label, delta))
    result = {"method": "paired group-cluster percentile bootstrap", "resampling_unit": "group_id with all paired sources kept together",
              "paired_sources": len(shared), "paired_groups": len(clusters), "requested_samples": samples,
              "valid_samples": 0, "invalid_samples": 0, "confidence_level": .95, "ci95": None, "reason": None}
    if len(clusters) < 2:
        result["reason"] = "At least two paired groups are required."
        return result
    if {label for cluster in clusters.values() for label, _ in cluster} != {0, 1}:
        result["reason"] = "Both classes are required among paired sources."
        return result
    if samples == 0:
        result["reason"] = "Bootstrap disabled."
        return result
    # Aggregate each group without splitting its members or repeated conditions.
    totals = []
    for key in sorted(clusters):
        members = clusters[key]
        totals.append([sum(label == 0 for label, _ in members), sum(label == 1 for label, _ in members),
                       sum(delta for label, delta in members if label == 0), sum(delta for label, delta in members if label == 1)])
    totals = np.asarray(totals, dtype=float)
    rng, deltas = np.random.default_rng(seed), []
    for _ in range(samples):
        counts = totals[rng.integers(0, len(totals), size=len(totals))].sum(axis=0)
        if min(counts[:2]) == 0:
            result["invalid_samples"] += 1
        else:
            deltas.append(float(.5 * (counts[2] / counts[0] + counts[3] / counts[1])))
    result["valid_samples"] = len(deltas)
    if len(deltas) >= max(2, math.ceil(samples * .9)):
        result["ci95"] = [float(value) for value in np.quantile(deltas, [.025, .975])]
    else:
        result["reason"] = "Fewer than 90% of bootstrap draws contain both classes; interval omitted."
    return result


def summarize_benchmark(protocol_path, detector_id):
    protocol = load_protocol(protocol_path)
    directory = Path(protocol_path).resolve().parent / "results" / detector_id
    rows = _read_journal(directory / "predictions.jsonl")
    failures = _read_journal(directory / "failures.jsonl")
    reports = {}
    for split in SPLITS:
        selected = [row for row in rows if row["split"] == split]
        report = evaluate_rows(selected, threshold=protocol["threshold"], bootstrap_samples=0, seed=protocol["seed"])
        for name, pair in report["paired_vs_baseline"].items():
            interval = grouped_paired_interval(selected, name, protocol["threshold"], protocol["bootstrap_samples"], protocol["seed"])
            pair["balanced_accuracy_delta_ci95"] = interval["ci95"]
            pair["bootstrap"] = interval
            pair["reason"] = interval["reason"]
        expected_sources = [row for row in protocol["sources"] if row["split"] == split]
        report["coverage"] = {"expected_sources": len(expected_sources), "expected_groups": len({row["group_id"] for row in expected_sources}),
                              "expected_predictions": len(expected_sources) * len(protocol["conditions"]), "actual_predictions": len(selected),
                              "complete": len(selected) == len(expected_sources) * len(protocol["conditions"])}
        reports[split] = report
    summary = {"protocol_hash": protocol["protocol_hash"], "detector_id": detector_id,
               "generated_at_utc": _now(), "failure_attempts": len(failures), "splits": reports,
               "cautions": ["Train metrics are apparent fit, not held-out performance.",
                            "Confidence intervals resample groups, retaining related real/generated sources.",
                            "Incomplete conditions describe available cases; inspect failures before scientific interpretation."]}
    directory.mkdir(parents=True, exist_ok=True)
    _write_predictions_csv(rows, directory / "predictions.csv")
    _atomic_json(directory / "summary.json", summary)
    return summary


def run_benchmark(protocol_path, detector, allowed_splits=None, max_new_scores=None, detector_id="bfree", retry_failures=False):
    """Resume exactly the frozen study, making at most max_new_scores new calls.

    A failure is recorded but never converted into a score. By default failed
    source/conditions remain failed on resume; retry_failures explicitly retries
    them while preserving earlier failure records. Cache hits cost no model call.
    """
    protocol_path = Path(protocol_path).resolve()
    protocol = load_protocol(protocol_path, verify_sources=True)
    splits = set(allowed_splits or ["test"])
    if not splits.issubset(SPLITS) or not splits:
        raise ValueError("Requested splits must be train, validation or test.")
    if max_new_scores is not None and (isinstance(max_new_scores, bool) or not isinstance(max_new_scores, int) or max_new_scores < 0):
        raise ValueError("max_new_scores must be a nonnegative integer or None.")
    if not detector.available:
        raise ValueError("A real configured detector is required; no substitute scores are permitted.")
    fingerprint = detector_fingerprint(detector)
    _check_detector(protocol, detector_id, fingerprint)
    model_hash = _digest(fingerprint)
    root = protocol_path.parent
    directory = root / "results" / detector_id
    directory.mkdir(parents=True, exist_ok=True)
    cache_dir = root / "cache"
    cache_dir.mkdir(exist_ok=True)
    counters = {"new_model_calls": 0, "cache_hits": 0, "new_predictions": 0, "new_failures": 0, "budget_exhausted": False}
    with _run_lock(root):
        metadata_path = directory / "model.json"
        if metadata_path.exists() and json.loads(metadata_path.read_text()) != fingerprint:
            raise ValueError("Existing prediction journal belongs to a different model fingerprint.")
        if not metadata_path.exists():
            _atomic_json(metadata_path, fingerprint)
        previous = _read_journal(directory / "predictions.jsonl")
        completed = set()
        for row in previous:
            key = (row["source_id"], row["condition"])
            if row["protocol_hash"] != protocol["protocol_hash"] or row["model_fingerprint_sha256"] != model_hash or key in completed:
                raise ValueError("Prediction journal contains conflicting provenance or duplicate source/condition rows.")
            completed.add(key)
        failed = {(row["source_id"], row["condition"]) for row in _read_journal(directory / "failures.jsonl")}
        with tempfile.TemporaryDirectory(prefix="benchmark-input-", dir=root) as temporary:
            stop = False
            for source in protocol["sources"]:
                if source["split"] not in splits:
                    continue
                image_data = Path(source["path"]).read_bytes()
                if hashlib.sha256(image_data).hexdigest() != source["sha256"]:
                    raise ValueError(f"Source changed during run: {source['source_id']}")
                original, _ = pipeline.decode_image(image_data)
                for condition in protocol["conditions"]:
                    key = (source["source_id"], condition["name"])
                    if key in completed or (key in failed and not retry_failures):
                        continue
                    base = {key: source[key] for key in ("source_id", "label", "generator", "group_id", "split")}
                    base.update(protocol_hash=protocol["protocol_hash"], detector_id=detector_id,
                                model_fingerprint_sha256=model_hash, condition=condition["name"], source_sha256=source["sha256"])
                    try:
                        image, content, fmt, operations = render_condition(original, condition)
                        pixel_hash = canonical_image_hash(image)
                        cache_key = _digest({"pixel_sha256": pixel_hash, "model": model_hash, "preprocess": fingerprint["preprocess_sha256"]})
                        cache_path = cache_dir / f"{cache_key}.json"
                        base.update(pixel_sha256=pixel_hash, cache_key=cache_key, artifact_sha256=hashlib.sha256(content).hexdigest(),
                                    width=image.width, height=image.height, format=fmt, operations=operations)
                        if cache_path.exists():
                            cached = json.loads(cache_path.read_text())
                            if cached.get("cache_key") != cache_key or cached.get("model_fingerprint_sha256") != model_hash or cached.get("pixel_sha256") != pixel_hash:
                                raise ValueError("Cached prediction provenance does not match its key.")
                            prediction = _valid_prediction(cached["prediction"])
                            origin = "cache"
                            counters["cache_hits"] += 1
                        else:
                            if max_new_scores is not None and counters["new_model_calls"] >= max_new_scores:
                                counters["budget_exhausted"] = stop = True
                                break
                            input_path = Path(temporary) / "input.png"
                            input_path.write_bytes(pipeline.encode(image, "PNG"))
                            counters["new_model_calls"] += 1
                            started = time.perf_counter()
                            prediction = _valid_prediction(detector.detect(input_path))
                            prediction.setdefault("runtime_seconds", time.perf_counter() - started)
                            origin = "inference"
                            _atomic_json(cache_path, {"cache_key": cache_key, "pixel_sha256": pixel_hash,
                                                     "model_fingerprint_sha256": model_hash, "prediction": prediction,
                                                     "created_at_utc": _now()})
                        row = {**base, "score": prediction["score"], "raw_logit": prediction.get("raw_logit"),
                               "prediction": prediction, "score_origin": origin, "recorded_at_utc": _now()}
                        _append(directory / "predictions.jsonl", row)
                        completed.add(key)
                        counters["new_predictions"] += 1
                    except Exception as exc:
                        _append(directory / "failures.jsonl", {**base, "error_type": type(exc).__name__, "error": str(exc), "recorded_at_utc": _now()})
                        counters["new_failures"] += 1
                if stop:
                    break
        summary = summarize_benchmark(protocol_path, detector_id)
    return {**counters, "protocol_hash": protocol["protocol_hash"], "detector_id": detector_id,
            "summary_path": str(directory / "summary.json"),
            "complete_requested_splits": all(summary["splits"][split]["coverage"]["complete"] for split in splits)}


def train_frequency_baseline(protocol_path):
    """Fit once on frozen train originals only; refuse replacing learned weights."""
    from .frequency_baseline import extract_features, fit_model, save_model, load_model
    protocol_path = Path(protocol_path).resolve()
    protocol = load_protocol(protocol_path, verify_sources=True)
    path = protocol_path.parent / "frequency-model.json"
    expected_ids = sorted(row["source_id"] for row in protocol["sources"] if row["split"] == "train")
    if path.exists():
        model = load_model(path)
        if model["protocol_hash"] != protocol["protocol_hash"] or sorted(model["training_source_ids"]) != expected_ids:
            raise ValueError("Existing frequency model has conflicting training provenance.")
        return path
    train = [row for row in protocol["sources"] if row["split"] == "train"]
    features = []
    for source in train:
        image, _ = pipeline.decode_image(Path(source["path"]).read_bytes())
        features.append(extract_features(image))
    model = fit_model(np.asarray(features), np.asarray([row["label"] for row in train]),
                      [row["source_id"] for row in train], protocol["protocol_hash"])
    save_model(model, path)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze", help="Hash data, code and model settings before scoring")
    freeze.add_argument("manifest", type=Path)
    freeze.add_argument("--output", required=True, type=Path)
    freeze.add_argument("--bootstrap-samples", type=int, default=2000)
    freeze.add_argument("--seed", type=int, default=2026)
    freeze.add_argument("--threshold", type=float, default=.5)
    run = commands.add_parser("run")
    run.add_argument("protocol", type=Path)
    run.add_argument("--detector", choices=("bfree", "frequency"), default="bfree")
    run.add_argument("--splits", nargs="+", choices=SPLITS, default=["test"])
    run.add_argument("--max-new-scores", type=int)
    run.add_argument("--retry-failures", action="store_true")
    summary = commands.add_parser("summary")
    summary.add_argument("protocol", type=Path)
    summary.add_argument("--detector", choices=("bfree", "frequency"), default="bfree")
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            from .detectors import choose_detector
            detector = choose_detector({})
            if not detector.available:
                raise ValueError(detector.reason)
            frozen = freeze_protocol(args.manifest, args.output, {"bfree_fingerprint": detector_fingerprint(detector),
                                     "threshold": args.threshold, "seed": args.seed, "bootstrap_samples": args.bootstrap_samples})
            result = {"protocol_path": str(args.output / "protocol.json"), "protocol_hash": frozen["protocol_hash"],
                      "sources": len(frozen["sources"]), "groups": len({row["group_id"] for row in frozen["sources"]}),
                      "conditions": len(frozen["conditions"]), "split_counts": dict(Counter(row["split"] for row in frozen["sources"]))}
        elif args.command == "run":
            if args.detector == "frequency":
                from .frequency_baseline import FrequencyDetector
                detector = FrequencyDetector(train_frequency_baseline(args.protocol))
            else:
                from .detectors import choose_detector
                detector = choose_detector({})
            result = run_benchmark(args.protocol, detector, args.splits, args.max_new_scores, args.detector, args.retry_failures)
        else:
            result = summarize_benchmark(args.protocol, args.detector)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
