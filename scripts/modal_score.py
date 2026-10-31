"""Score the frozen test split on Modal CUDA and write the frozen prediction schema.

One Modal call scores one (source, condition) pair. Rendering goes through
``forensics.benchmark.render_condition`` and scoring through the installed
``BFreeDetector``, so pixels and adapter match the local pilot. Failures are
returned as records, never converted into a score.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from forensics import pipeline
from forensics.benchmark import DEFAULT_CONDITIONS, render_condition

APP_NAME = "ai-forensics-modal-batch"
MODEL_VOLUME = "ai-forensics-models"
MODEL_ROOT = "/models"
CHECKPOINT_DIR = f"{MODEL_ROOT}/BFREE_dino2reg4"
BFREE_DIR = "/bfree"
BFREE_REVISION = "c6a9f898782fb466b29af01f21960b67415afb0e"
DATA_ROOT = "/data"
GPU = "T4"
COLUMNS = ("source_id", "label", "generator", "group_id", "split", "condition", "score", "raw_logit")
MANIFEST_COLUMNS = ("source_id", "path", "label", "generator", "group_id", "split", "sha256")
MANIFEST_PATH = ROOT / "data" / "benchmark" / "manifest.csv"
EXPECTED_TEST_SOURCES = 192
PILOT_CHECKPOINT_SHA256 = "5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947"
PIP_PINS = ("torch==2.5.1", "torchvision==0.20.1", "timm==1.0.12", "transformers==4.43.4",
            "numpy==1.26.4", "Pillow", "PyYAML")
CONDITION_ORDER = tuple(condition["name"] for condition in DEFAULT_CONDITIONS)
FROZEN_RECIPES = {
    condition["name"]: {key: condition[key] for key in ("name", "operation", "quality", "scale", "rounds", "mode", "order")}
    for condition in DEFAULT_CONDITIONS
}

_DETECTOR = None


class MissingTokenError(RuntimeError):
    """Modal credentials are not available in this environment."""


def require_modal_token(environ=None):
    """Refuse to start without credentials, before touching Modal or the data."""
    environ = os.environ if environ is None else environ
    missing = [name for name in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET") if not environ.get(name)]
    if missing:
        raise MissingTokenError(
            "Modal credentials are missing: " + " and ".join(missing) + ". "
            "Run `modal setup` (or `modal token new`), then export both values from ~/.modal.toml or the Modal dashboard."
        )


def condition_recipes(conditions=None):
    """Map the nine frozen condition names to their recipes, and refuse any other set."""
    conditions = DEFAULT_CONDITIONS if conditions is None else conditions
    by_name = {}
    for raw in conditions:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            raise ValueError("Every frozen condition needs a name.")
        if raw["name"] in by_name:
            raise ValueError(f"Duplicate frozen condition: {raw['name']}")
        by_name[raw["name"]] = raw
    missing = sorted(set(CONDITION_ORDER) - set(by_name))
    unexpected = sorted(set(by_name) - set(CONDITION_ORDER))
    if missing or unexpected:
        raise ValueError(f"Conditions are not the nine frozen ones; missing {missing}, unexpected {unexpected}.")
    recipes = {}
    for name in CONDITION_ORDER:
        recipe = {key: by_name[name].get(key) for key in FROZEN_RECIPES[name]}
        if recipe != FROZEN_RECIPES[name]:
            raise ValueError(f"Condition {name} does not match its frozen recipe.")
        recipes[name] = recipe
    return recipes


def test_sources(manifest_path, expected=EXPECTED_TEST_SOURCES):
    """Return test sources with manifest-relative paths and verified image bytes."""
    path = Path(manifest_path).resolve()
    if not path.is_file():
        raise ValueError(f"Manifest not found: {path}. Acquire the dataset with scripts/acquire_benchmark.py first.")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = [name.strip() for name in reader.fieldnames or []]
        if not set(MANIFEST_COLUMNS).issubset(headers) or len(headers) != len(set(headers)):
            raise ValueError("Manifest needs unique " + ", ".join(MANIFEST_COLUMNS) + " columns.")
        reader.fieldnames = headers
        rows = list(reader)
    sources, seen = [], set()
    for row in rows:
        if (row.get("split") or "").strip() != "test":
            continue
        source_id = (row.get("source_id") or "").strip()
        if not source_id or source_id in seen:
            raise ValueError(f"Manifest has a blank or duplicate test source_id: {source_id!r}")
        seen.add(source_id)
        if (row.get("label") or "").strip() not in {"0", "1"}:
            raise ValueError(f"Test source {source_id} needs label 0 or 1.")
        generator = (row.get("generator") or "").strip()
        group_id = (row.get("group_id") or "").strip()
        if not generator or not group_id:
            raise ValueError(f"Test source {source_id} needs a generator and group_id.")
        checksum = (row.get("sha256") or "").strip().lower()
        if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            raise ValueError(f"Test source {source_id} needs a lowercase SHA-256 checksum.")
        relative = PurePosixPath((row.get("path") or "").strip())
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Test source {source_id} must point inside the manifest directory.")
        file = path.parent / relative.as_posix()
        if not file.is_file():
            raise ValueError(f"Test image is missing: {file}. Acquire the dataset before running this batch.")
        if hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Test image checksum mismatch: {source_id} at {file}.")
        sources.append({"source_id": source_id, "label": int(row["label"]), "generator": generator,
                        "group_id": group_id, "split": "test", "path": relative.as_posix(),
                        "sha256": checksum})
    if not sources:
        raise ValueError("Manifest contains no test sources.")
    if expected is not None and len(sources) != expected:
        raise ValueError(f"Expected {expected} test sources and found {len(sources)}; the delivered split changed.")
    return sorted(sources, key=lambda source: source["source_id"])


def build_tasks(sources, recipes, smoke=False):
    """One task per source and condition, in frozen condition order."""
    selected = sources[:1] if smoke else sources
    return [
        {**{key: source[key] for key in ("source_id", "label", "generator", "group_id", "split", "path", "sha256")},
         "condition": name, "recipe": recipe}
        for source in selected
        for name, recipe in recipes.items()
    ]


def prediction_row(task, prediction):
    """Build the eight frozen CSV fields from one validated detector response."""
    if not isinstance(prediction, dict):
        raise ValueError("Detector returned no prediction mapping.")
    score = prediction.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Detector score must be a finite number in [0, 1].")
    raw_logit = prediction.get("raw_logit")
    if raw_logit is not None:
        if isinstance(raw_logit, bool) or not isinstance(raw_logit, (int, float)) or not math.isfinite(raw_logit):
            raise ValueError("Detector raw_logit must be finite.")
        raw_logit = float(raw_logit)
    return {"source_id": task["source_id"], "label": task["label"], "generator": task["generator"],
            "group_id": task["group_id"], "split": task["split"], "condition": task["condition"],
            "score": float(score), "raw_logit": raw_logit}


def score_task(task, detector, data_root=DATA_ROOT):
    """Render one frozen condition from one delivered source and score its pixels."""
    data = (Path(data_root) / task["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != task["sha256"]:
        raise ValueError(f"Source changed after the manifest was read: {task['source_id']}")
    original, _ = pipeline.decode_image(data)
    image, _content, _format, _history = render_condition(original, task["recipe"])
    with tempfile.TemporaryDirectory(prefix="modal-score-") as temporary:
        input_path = Path(temporary) / "input.png"
        input_path.write_bytes(pipeline.encode(image, "PNG"))
        prediction = detector.detect(input_path)
    return prediction_row(task, prediction), prediction


def probe_detector(detector):
    """Load the volume checkpoint with one real GPU inference and report its identity."""
    import torch

    with tempfile.TemporaryDirectory(prefix="modal-probe-") as temporary:
        path = Path(temporary) / "probe.png"
        Image.new("RGB", (64, 64), (127, 127, 127)).save(path)
        prediction = detector.detect(path)
    return {"model": prediction.get("model"), "model_revision": prediction.get("model_revision"),
            "checkpoint_sha256": prediction.get("checkpoint_sha256"), "device": prediction.get("device"),
            "torch": torch.__version__, "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "runtime_seconds": prediction.get("runtime_seconds")}


def _get_detector():
    global _DETECTOR
    if _DETECTOR is None:
        from forensics.detectors import BFreeDetector
        _DETECTOR = BFreeDetector(BFREE_DIR, CHECKPOINT_DIR, device="cuda")
    return _DETECTOR


def write_predictions(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["source_id"], row["condition"])))
    return path


def _write_jsonl(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
    return path


def _failure(task, error_type, error):
    return {"source_id": task["source_id"], "condition": task["condition"], "error_type": error_type, "error": error}


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _image(modal, local_root, keep):
    """Pinned CUDA image. Weights stay in the read-only volume, never here."""
    return (
        modal.Image.from_registry("python:3.12-slim")
        .apt_install("git")
        .pip_install(*PIP_PINS)
        .run_commands(
            f"git clone https://github.com/grip-unina/B-Free.git {BFREE_DIR}",
            f"git -C {BFREE_DIR} checkout {BFREE_REVISION}",
        )
        .add_local_python_source("forensics")
        .add_local_dir(str(local_root), DATA_ROOT, ignore=lambda path: path.as_posix() not in keep)
    )


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="Frozen benchmark manifest.")
    parser.add_argument("--output", type=Path, required=True, help="Predictions CSV to write, outside output/.")
    parser.add_argument("--smoke", action="store_true", help="Score the first test source under all nine conditions.")
    return parser


def main(argv=None, environ=None):
    args = _parser().parse_args(argv)
    require_modal_token(os.environ if environ is None else environ)
    recipes = condition_recipes()
    manifest = Path(args.manifest).resolve()
    sources = test_sources(manifest)
    tasks = build_tasks(sources, recipes, smoke=args.smoke)
    output = Path(args.output).expanduser().resolve()
    keep = {task["path"] for task in tasks}

    import modal

    app = modal.App(APP_NAME)
    image = _image(modal, manifest.parent, keep)
    models = modal.Volume.from_name(MODEL_VOLUME).with_mount_options(read_only=True)
    retries = modal.Retries(max_retries=2)

    @app.function(image=image, gpu=GPU, volumes={MODEL_ROOT: models}, max_containers=2,
                  timeout=900, retries=retries)
    def probe():
        return probe_detector(_get_detector())

    @app.function(image=image, gpu=GPU, volumes={MODEL_ROOT: models}, max_containers=2,
                  timeout=900, retries=retries)
    def score_one(task: dict) -> dict:
        try:
            row, response = score_task(task, _get_detector())
            return {"row": row, "response": response, "error": None}
        except Exception as exc:
            return {"row": None, "response": None,
                    "error": _failure(task, type(exc).__name__, str(exc))}

    started = time.perf_counter()
    with app.run():
        info = probe.remote()
        print(json.dumps({"probe": info}, indent=2, allow_nan=False), flush=True)
        scores_started = time.perf_counter()
        results = list(score_one.map(tasks, return_exceptions=True))
        scoring_seconds = time.perf_counter() - scores_started
    elapsed_seconds = time.perf_counter() - started

    if info.get("checkpoint_sha256") != PILOT_CHECKPOINT_SHA256:
        print(f"warning: checkpoint is {info.get('checkpoint_sha256')}, not the pilot's {PILOT_CHECKPOINT_SHA256}; "
              "point estimates are not like-for-like.", flush=True)

    rows, responses, failures = [], [], []
    for task, result in zip(tasks, results):
        if isinstance(result, BaseException):
            failures.append(_failure(task, type(result).__name__, str(result)))
        elif result.get("error"):
            failures.append(result["error"])
        else:
            rows.append(result["row"])
            responses.append(result["response"])

    if args.smoke:
        for response in responses:
            print(json.dumps(response, indent=2, allow_nan=False), flush=True)

    predictions_path = write_predictions(rows, output)
    failures_path = _write_jsonl(failures, output.with_suffix(".failures.jsonl")) if failures else None
    runtimes = [response["runtime_seconds"] for response in responses if response.get("runtime_seconds") is not None]
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "device": info.get("device"), "gpu": info.get("gpu"), "torch": info.get("torch"), "cuda": info.get("cuda"),
        "model": info.get("model"), "model_revision": info.get("model_revision"),
        "checkpoint_sha256": info.get("checkpoint_sha256"),
        "pilot_checkpoint_sha256": PILOT_CHECKPOINT_SHA256,
        "manifest_path": str(manifest), "manifest_sha256": _file_sha256(manifest),
        "columns": list(COLUMNS), "conditions": recipes,
        "sources": len({task["source_id"] for task in tasks}), "requests": len(tasks),
        "predictions": len(rows), "failures": len(failures),
        "smoke": bool(args.smoke), "scoring_seconds": round(scoring_seconds, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "inference_seconds": {"calls": len(runtimes), "median": round(statistics.median(runtimes), 4),
                              "max": round(max(runtimes), 4), "total": round(sum(runtimes), 3)}
                             if runtimes else None,
    }
    meta_path = output.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    print(json.dumps({"predictions": str(predictions_path), "rows": len(rows), "sources": meta["sources"],
                      "failures": len(failures), "failures_path": str(failures_path) if failures_path else None,
                      "meta": str(meta_path), "scoring_seconds": round(scoring_seconds, 3),
                      "elapsed_seconds": round(elapsed_seconds, 3)}, indent=2, allow_nan=False), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MissingTokenError as exc:
        raise SystemExit(f"modal_score: {exc}")
