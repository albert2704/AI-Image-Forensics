"""Run one image or a labeled manifest without the UI."""
import argparse
import csv
import json
from pathlib import Path

from .detectors import choose_detector
from .pipeline import analyze


def read_manifest(path: Path) -> list[dict[str, str]]:
    """Validate and normalize all source metadata before running any inference."""
    required = ("source_id", "path", "label", "generator")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, strict=True)
        if not reader.fieldnames:
            raise ValueError("Manifest needs a header with source_id,path,label,generator.")
        headers = [name.strip() for name in reader.fieldnames]
        if any(not name for name in headers) or len(headers) != len(set(headers)):
            raise ValueError("Manifest header names must be nonempty and unique.")
        missing = set(required) - set(headers)
        if missing:
            raise ValueError(f"Manifest is missing required columns: {', '.join(sorted(missing))}.")
        reader.fieldnames = headers
        rows = []
        seen_ids = set()
        for row in reader:
            line = reader.line_num
            if None in row:
                raise ValueError(f"Manifest line {line} has more values than header columns.")
            normalized = {}
            for key in required:
                value = row.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Manifest line {line}: {key} must be nonempty.")
                normalized[key] = value.strip()
            if normalized["label"] not in {"0", "1"}:
                raise ValueError(f"Manifest line {line}: label must be 0 or 1.")
            if normalized["source_id"] in seen_ids:
                raise ValueError("Every original needs a unique source_id after trimming whitespace.")
            seen_ids.add(normalized["source_id"])
            rows.append(normalized)
    if not rows:
        raise ValueError("Manifest contains no source images.")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path)
    source.add_argument("--manifest", type=Path, help="CSV: source_id,path,label,generator; paths relative to the manifest")
    parser.add_argument("--output", type=Path, default=Path("output/runs"))
    parser.add_argument("--quality", type=int, default=90)
    parser.add_argument("--scale", type=float, default=.9)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--mode", choices=["cumulative", "independent"], default="cumulative")
    parser.add_argument("--operation", choices=["combined", "jpeg", "resize"], default="combined")
    parser.add_argument("--order", choices=["resize-jpeg", "jpeg-resize"], default="resize-jpeg")
    parser.add_argument("--threshold", type=float, default=.5)
    args = parser.parse_args()
    config = vars(args)
    if args.image:
        detector = choose_detector({})
        report = analyze(args.image.read_bytes(), args.image.name, config, args.output, detector)
        print(json.dumps({"run_id": report["run_id"], "summary": report["summary"], "path": str(args.output / report["run_id"] / "report.json")}, indent=2))
        return
    try:
        rows = read_manifest(args.manifest)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    detector = choose_detector({})
    if not detector.available:
        parser.error("Batch evaluation requires B-Free. Configure the checkpoint first; missing scores cannot be evaluated.")
    seen_hashes = set()
    args.output.mkdir(parents=True, exist_ok=True)
    predictions = []
    for row in rows:
        path = (args.manifest.parent / row["path"]).resolve()
        report = analyze(path.read_bytes(), path.name, config, args.output, detector)
        if report["image"]["sha256"] in seen_hashes:
            parser.error("Duplicate original bytes found under different source IDs.")
        seen_hashes.add(report["image"]["sha256"])
        for variant in report["variants"]:
            if variant["score"] is None:
                parser.error(f"Missing model score for {row['source_id']}; inspect run {report['run_id']}.")
            condition = "baseline" if variant["round"] == 0 else f"{args.operation}_{args.mode}_{args.order}_q{args.quality}_s{args.scale}_r{variant['round']}"
            predictions.append({"source_id": row["source_id"], "label": row["label"], "generator": row["generator"],
                                "condition": condition, "score": variant["score"], "run_id": report["run_id"]})
    with (args.output / "predictions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_id", "label", "generator", "condition", "score", "run_id"])
        writer.writeheader()
        writer.writerows(predictions)
    print(f"Wrote {len(predictions)} predictions to {args.output / 'predictions.csv'}")


if __name__ == "__main__":
    main()
