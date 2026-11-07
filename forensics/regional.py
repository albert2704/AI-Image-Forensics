"""Publish regional detector artifacts without leaking local filesystem paths.

The TruFor adapter returns absolute paths for its own use. A served report only
needs URLs, so the paths stop here. This lives outside detectors.py because the
frozen B-Free benchmark hashes that file's bytes.
"""

from __future__ import annotations

from pathlib import Path
import shutil

REGIONAL_PATH_KEYS = ("heatmap_path", "reliability_path", "overlay_path", "npz_path")


def publish_regional(result: dict, directory, run_id: str, prefix: str) -> dict:
    """Copy regional PNGs into the run directory and return a record with no local paths."""
    record = {key: value for key, value in result.items() if key not in REGIONAL_PATH_KEYS}
    root = Path(directory).resolve()
    for key in ("heatmap", "reliability", "overlay"):
        local = result.get(f"{key}_path")
        if not local:
            continue
        source = Path(local).resolve()
        if not source.is_relative_to(root) or source.suffix.lower() != ".png" or not source.is_file():
            raise ValueError("Regional adapter returned an unexpected artifact path.")
        published = root / f"{prefix}{key}.png"
        shutil.copyfile(source, published)
        record[f"{key}_url"] = f"/runs/{run_id}/{published.name}"
    return record
