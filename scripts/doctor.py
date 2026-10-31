"""Report which parts of this checkout are present, and what each missing piece blocks."""

from __future__ import annotations

import csv
import json
from importlib import metadata
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
PLANNER_FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json")


def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def read_json(path):
    """Return parsed JSON, or None when the file is missing, unreadable or malformed."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def find_run(root, run_id):
    for base in (root / "output" / "runs", root / "output" / "model-verification"):
        if (base / run_id).is_dir():
            return base / run_id
    return None


def collect(root=ROOT):
    root = Path(root)
    rows = []

    def add(name, status, detail):
        rows.append({"name": name, "status": status, "detail": detail})

    add("python", "ok", platform.python_version())
    protocol = read_json(root / "output" / "benchmark" / "protocol.json")
    fingerprint = protocol.get("code_fingerprint") if isinstance(protocol, dict) else None
    frozen = fingerprint.get("python") if isinstance(fingerprint, dict) else None
    if frozen and frozen != platform.python_version():
        rows[0].update(status="warn", detail=f"{platform.python_version()}, protocol froze {frozen}")

    for name in ("numpy", "pillow"):
        found = version(name)
        add(name, "ok" if found else "missing", found or "not installed")

    manifest = root / "data" / "benchmark" / "manifest.csv"
    if manifest.is_file():
        with manifest.open(newline="", encoding="utf-8") as stream:
            paths = [row["path"] for row in csv.DictReader(stream)]
        present = sum(1 for path in paths if (manifest.parent / path).is_file())
        status = "ok" if present == len(paths) else "missing" if not present else "partial"
        add("images", status, f"{present} of {len(paths)} manifest files under data/benchmark/")
    else:
        add("images", "missing", "no data/benchmark/manifest.csv")

    runs = root / "output" / "runs"
    try:
        count = len([entry for entry in runs.iterdir() if entry.is_dir()]) if runs.is_dir() else 0
        add("your runs", "ok" if count else "missing", f"{count} directories under output/runs")
    except OSError as exc:
        add("your runs", "missing", f"cannot read output/runs: {exc.strerror or exc}")

    pointer_path = root / "output" / "verified-example.json"
    pointer = read_json(pointer_path)
    run_id = pointer.get("run_id") if isinstance(pointer, dict) else None
    if not pointer_path.is_file():
        add("demo example", "missing", "no output/verified-example.json")
    elif not isinstance(run_id, str):
        add("demo example", "missing", "the recorded example pointer is invalid")
    else:
        location = find_run(root, run_id)
        add("demo example", "ok" if location else "missing", str(location.relative_to(root)) if location else f"run {run_id} not found")

    bfree = os.environ.get("BFREE_REPO") or str(root / "external" / "B-Free")
    add("B-Free", "ok" if Path(bfree).is_dir() else "missing", bfree)

    trufor_env = os.environ.get("TRUFOR_REPO")
    trufor = Path(trufor_env).expanduser() if trufor_env else root / "external" / "TruFor"
    entry = trufor / "TruFor_train_test" / "test.py"
    weights = trufor / "TruFor_train_test" / "pretrained_models" / "trufor.pth.tar"
    add("TruFor", "ok" if entry.is_file() and weights.is_file() else "missing", str(trufor))

    planner = root / "external" / "Qwen2.5-1.5B-Instruct"
    installed = all((planner / name).is_file() for name in PLANNER_FILES)
    add("planner", "ok" if installed else "missing", str(planner))
    return rows


BLOCKS = {
    "images": "benchmark resume",
    "your runs": "reopening a fixed run from an older session",
    "demo example": "the recorded demo button",
    "B-Free": "AI scores on any upload",
    "TruFor": "regional scans",
    "planner": "adaptive investigations",
}


def render(rows):
    lines = []
    for row in rows:
        detail = row["detail"]
        if row["status"] != "ok" and row["name"] in BLOCKS:
            detail = f"{detail} (blocks {BLOCKS[row['name']]})"
        lines.append(f"{row['name']:<12} {row['status']:<7} {detail}")
    return "\n".join(lines)


def main():
    rows = collect()
    print(render(rows))
    missing = [row["name"] for row in rows if row["status"] == "missing"]
    print()
    print("All present." if not missing else f"Missing: {', '.join(missing)}. See docs/MODEL_SETUP.md and README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
