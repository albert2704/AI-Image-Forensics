#!/usr/bin/env python3
"""Audit acquired source bytes, grouping and duplicate candidates without scoring.

The pHash screen is only a candidate screen, not proof of independence. It never
removes or replaces a prespecified image. No detector is imported or executed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zlib

import numpy as np
from PIL import Image
from scipy.fft import dctn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forensics.pipeline import decode_image


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def audit(manifest):
    manifest = Path(manifest).resolve()
    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    plan_path = manifest.parent / "metadata" / "selection-plan.json"
    plan = json.loads(plan_path.read_text())
    expected = {row["source_id"]: row for row in plan["selection"]}
    if len(rows) != 320 or len({r["source_id"] for r in rows}) != 320 or set(expected) != {r["source_id"] for r in rows}:
        raise ValueError("Manifest does not contain exactly the prespecified 320 unique images.")
    groups, pixel_ids, perceptual, dimensions, modes, samples = defaultdict(list), defaultdict(list), [], defaultdict(Counter), Counter(), []
    for row in rows:
        for key in ("path", "label", "generator", "group_id", "split", "source_url", "archive_member", "paired_generator"):
            if str(row[key]) != str(expected[row["source_id"]][key]):
                raise ValueError(f"Selection mismatch: {row['source_id']} / {key}")
        path = (manifest.parent / row["path"]).resolve(strict=True)
        if not path.is_relative_to(manifest.parent):
            raise ValueError("Image is outside the acquired dataset.")
        blob = path.read_bytes()
        if sha256(blob) != row["sha256"] or len(blob) != int(row["bytes"]) or zlib.crc32(blob) & 0xFFFFFFFF != int(row["crc32"]):
            raise ValueError(f"Image bytes differ from manifest: {row['source_id']}")
        image, info = decode_image(blob)
        if image.size != (int(row["width"]), int(row["height"])):
            raise ValueError("Decoded dimensions differ from manifest.")
        header = json.dumps({"mode": "RGB", "size": list(image.size)}, sort_keys=True, separators=(",", ":")).encode()
        normalized_hash = sha256(header + image.tobytes())
        pixel_ids[normalized_hash].append(row["source_id"])
        gray = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
        coefficients = dctn(gray, type=2, norm="ortho")[:8, :8].ravel()[1:]
        bits = coefficients > np.median(coefficients)
        phash = sum(int(bit) << index for index, bit in enumerate(bits))
        perceptual.append((row, phash))
        samples.append({"source_id": row["source_id"], "normalized_pixel_sha256": normalized_hash, "phash63": f"{phash:016x}"})
        groups[row["group_id"]].append(row)
        dimensions[row["generator"]][f"{image.width}x{image.height}"] += 1
        modes[info["source_mode"]] += 1
    duplicates = [ids for ids in pixel_ids.values() if len(ids) > 1]
    if duplicates:
        raise ValueError(f"Exact normalized duplicate images: {duplicates}")
    if len(groups) != 160:
        raise ValueError("Expected 160 distinct matched source groups.")
    prompt_path = manifest.parent / "metadata" / "Synthbuster-prompts.csv"
    with prompt_path.open(newline="", encoding="utf-8-sig") as stream:
        prompts = list(csv.DictReader(stream))
    prompt_ids = [row["image name (matching Raise-1k)"] for row in prompts]
    if len(prompt_ids) != len(set(prompt_ids)) or not {group.split(":", 1)[1] for group in groups}.issubset(prompt_ids):
        raise ValueError("Selected matched groups are missing or ambiguous in the source prompt CSV.")
    for group, members in groups.items():
        if len(members) != 2 or {r["label"] for r in members} != {"0", "1"} or len({r["split"] for r in members}) != 1 or len({r["paired_generator"] for r in members}) != 1:
            raise ValueError(f"Invalid matched group or split leakage: {group}")
    candidates = []
    for index, (left, left_hash) in enumerate(perceptual):
        for right, right_hash in perceptual[index + 1:]:
            if left["group_id"] == right["group_id"]:
                continue
            distance = (left_hash ^ right_hash).bit_count()
            if distance <= 4:
                candidates.append({"left_source_id": left["source_id"], "right_source_id": right["source_id"], "hamming_distance": distance, "cross_split": left["split"] != right["split"]})
    return {"status": "passed_integrity", "audited_at_utc": datetime.now(timezone.utc).isoformat(),
            "manifest_sha256": sha256(manifest.read_bytes()), "selection_plan_sha256": sha256(plan_path.read_bytes()),
            "audit_script_sha256": sha256(Path(__file__).read_bytes()), "images": len(rows), "groups": len(groups),
            "total_image_bytes": sum(int(row["bytes"]) for row in rows), "labels": dict(Counter(r["label"] for r in rows)),
            "splits": dict(Counter(r["split"] for r in rows)), "generator_counts": dict(Counter(r["generator"] for r in rows)),
            "split_generator_counts": dict(Counter(f"{r['split']}:{r['generator']}" for r in rows)),
            "dimensions_by_generator": {key: dict(value) for key, value in dimensions.items()}, "source_modes": dict(modes),
            "exact_normalized_duplicate_groups": duplicates, "groups_crossing_splits": 0,
            "selected_groups_verified_against_source_prompt_csv": len(groups), "source_prompt_csv_sha256": sha256(prompt_path.read_bytes()),
            "perceptual_screen": {"method": "32x32 luminance LANCZOS, orthonormal 2D DCT; top-left 8x8 excluding DC; median threshold; cross-group Hamming distance <= 4 of 63 bits",
                                  "candidates": candidates, "limitation": "Heuristic candidate screen only. A negative screen does not establish absence of semantic, event or burst dependence. No images were removed or substituted."},
            "samples": samples, "no_detector_scores_computed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    report = audit(args.manifest)
    output = args.manifest.resolve().parent / "metadata" / "integrity-audit.json"
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, indent=2))
    print(f"Audit saved: {output}")


if __name__ == "__main__":
    main()
