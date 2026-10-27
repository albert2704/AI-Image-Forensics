#!/usr/bin/env python3
"""Acquire a prespecified 320-image pilot by HTTP ranges, without model scoring.

Only selected ZIP members are transferred. The acquisition refuses a server that
ignores Range, validates ZIP CRCs, preserves image bytes, and never substitutes a
different image after a failed download. Requires requests and Pillow.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import threading
import time
from urllib.parse import urlparse
import zipfile
import zlib

import requests
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from PIL import Image


SEED = 20261018
GROUPS = 160
GENERATORS = ("dalle3", "firefly", "midjourney-v5", "stable-diffusion-xl")
SOURCES = {
    "synthbuster": "https://zenodo.org/records/10066460/files/synthbuster.zip?download=1",
    "raise": "https://www.grip.unina.it/download/prog/B-Free/extended_synthbuster/real_RAISE_1k.zip",
}
PAGES = {
    "synthbuster": "https://zenodo.org/records/10066460",
    "raise": "https://github.com/grip-unina/B-Free#dataset-of-new-generators",
}
SOURCE_PREPROCESSING = {
    "synthbuster": "Original released PNG; authors report no JPEG compression or resampling after generation.",
    "raise": "Official GRIP release of RAISE-1k; already resized by dataset provider to approximately 1024x1024 area.",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rank(stem: str, purpose: str = "selection") -> str:
    key = f"forensics-pilot-v1|{SEED}|{stem}" if purpose == "selection" else f"forensics-pilot-v1|{SEED}|{purpose}|{stem}"
    return digest(key.encode())


def save_json(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


class RangeClient:
    def __init__(self, budget: int):
        self.budget = budget
        self.requested_bytes = 0
        self.received_bytes = 0
        self.lock = threading.Lock()
        self.next_by_host = {}
        self.local = threading.local()

    def session(self):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
            self.local.session.headers.update({"User-Agent": "AIImageForensicsResearchPilot/1.0", "Accept-Encoding": "identity"})
        return self.local.session

    def metadata(self, url):
        response = self.session().head(url, timeout=60, allow_redirects=True)
        response.raise_for_status()
        return {"url": url, "size": int(response.headers["Content-Length"]), "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}

    def get(self, metadata, start, count):
        count = min(count, metadata["size"] - start)
        if count <= 0:
            return b""
        host = urlparse(metadata["url"]).netloc
        for attempt in range(4):
            with self.lock:
                if self.requested_bytes + count > self.budget:
                    raise RuntimeError("Acquisition transfer budget exhausted; no full archive fallback is allowed.")
                self.requested_bytes += count
                now = time.monotonic()
                delay = max(0, self.next_by_host.get(host, now) - now)
                self.next_by_host[host] = now + delay + 0.65
            if delay:
                time.sleep(delay)
            headers = {"Range": f"bytes={start}-{start + count - 1}"}
            if metadata.get("etag"):
                headers["If-Match"] = metadata["etag"]
            try:
                response = self.session().get(metadata["url"], headers=headers, timeout=(30, 120), stream=True)
                if response.status_code in (429, 500, 502, 503, 504):
                    wait = min(60, max(2 ** attempt, int(response.headers.get("Retry-After", "1"))))
                    response.close()
                    time.sleep(wait)
                    continue
                if response.status_code != 206:
                    response.close()
                    raise RuntimeError(f"Expected HTTP 206 for a bounded range, received {response.status_code}; refused full download.")
                expected = f"bytes {start}-{start + count - 1}/{metadata['size']}"
                if response.headers.get("Content-Range") != expected:
                    response.close()
                    raise RuntimeError("Unexpected Content-Range or changed remote archive.")
                content = response.raw.read(count + 1)
                response.close()
                if len(content) != count:
                    raise OSError("Truncated range response.")
                with self.lock:
                    self.received_bytes += len(content)
                return content
            except (requests.RequestException, Urllib3HTTPError, OSError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Range request failed after four bounded attempts.")


class RemoteIndex(io.RawIOBase):
    def __init__(self, client, metadata):
        self.client = client
        self.metadata = metadata
        self.position = 0

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.metadata["size"] + offset
        return self.position

    def read(self, count=-1):
        count = self.metadata["size"] - self.position if count < 0 else count
        if count > 5_000_000:
            raise RuntimeError("Unexpectedly large ZIP index read.")
        result = self.client.get(self.metadata, self.position, count)
        self.position += len(result)
        return result


def read_index(client, metadata):
    with zipfile.ZipFile(RemoteIndex(client, metadata)) as archive:
        return {info.filename: {"archive_member": info.filename, "file_size": info.file_size, "compressed_size": info.compress_size, "crc32": info.CRC, "header_offset": info.header_offset, "compression": info.compress_type} for info in archive.infolist() if not info.is_dir()}


def read_member(client, metadata, member):
    # One bounded request normally includes the local header and entire payload.
    raw = client.get(metadata, member["header_offset"], member["compressed_size"] + 4096)
    header = struct.unpack("<4s5H3I2H", raw[:30])
    if header[0] != b"PK\x03\x04" or header[2] & 1:
        raise ValueError("Invalid or encrypted ZIP member.")
    payload_start = 30 + header[-2] + header[-1]
    payload_end = payload_start + member["compressed_size"]
    if payload_end > len(raw):
        raw += client.get(metadata, member["header_offset"] + len(raw), payload_end - len(raw))
    filename = raw[30:30 + header[-2]].decode("utf-8" if header[2] & 0x800 else "cp437")
    if filename != member["archive_member"] or header[3] != member["compression"]:
        raise ValueError("ZIP local header does not match frozen index.")
    blob = raw[payload_start:payload_end]
    if member["compression"] == zipfile.ZIP_DEFLATED:
        blob = zlib.decompress(blob, -15)
    elif member["compression"] != zipfile.ZIP_STORED:
        raise ValueError("Unsupported ZIP compression.")
    if len(blob) != member["file_size"] or zlib.crc32(blob) & 0xFFFFFFFF != member["crc32"]:
        raise ValueError("ZIP member size or CRC mismatch.")
    return blob


def selection(indexes):
    common = {PurePosixPath(name).stem for name in indexes["raise"] if name.endswith(".png")}
    for generator in GENERATORS:
        common &= {PurePosixPath(name).stem for name in indexes["synthbuster"] if name.startswith(f"synthbuster/{generator}/") and name.endswith(".png")}
    if len(common) != 1000:
        raise ValueError(f"Expected 1000 verified filename-matched source groups; found {len(common)}.")
    stems = sorted(common, key=rank)[:GROUPS]
    family_stems = {generator: [stem for index, stem in enumerate(stems) if GENERATORS[index % len(GENERATORS)] == generator] for generator in GENERATORS}
    rows = []
    for generator in GENERATORS:
        for index, stem in enumerate(sorted(family_stems[generator], key=lambda item: rank(item, "split"))):
            split = "train" if index < 8 else "validation" if index < 16 else "test"
            for source, label, category, member in (
                ("raise", 0, "real", f"real_RAISE_1k/{stem}.png"),
                ("synthbuster", 1, generator, f"synthbuster/{generator}/{stem}.png"),
            ):
                rows.append({"source_id": f"{source}:{category}:{stem}", "path": f"images/{category}/{stem}.png", "label": label, "generator": category, "group_id": f"raise1k:{stem}", "split": split, "source_url": SOURCES[source], "source": source, "paired_generator": generator, "origin_page": PAGES[source], "source_preprocessing": SOURCE_PREPROCESSING[source], **indexes[source][member]})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/benchmark"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-download-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    metadata_dir = root / "metadata"
    metadata_dir.mkdir(exist_ok=True)
    client = RangeClient(args.max_download_bytes)
    plan_path = metadata_dir / "selection-plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan["seed"] != SEED or plan["groups"] != GROUPS or tuple(plan["generators"]) != GENERATORS:
            raise ValueError("Existing selection plan does not match this acquisition protocol.")
        archives, rows = plan["archives"], plan["selection"]
        indexes = {name: json.loads((metadata_dir / f"{name}-index.json").read_text()) for name in SOURCES}
        for name, url in SOURCES.items():
            if client.metadata(url) != archives[name]:
                raise ValueError("Remote archive identity changed after selection freeze.")
    else:
        archives = {name: client.metadata(url) for name, url in SOURCES.items()}
        indexes = {name: read_index(client, archives[name]) for name in SOURCES}
        rows = selection(indexes)
        for name, index in indexes.items():
            save_json(metadata_dir / f"{name}-index.json", index)
        plan = {"version": "forensics-pilot-v1", "seed": SEED, "groups": GROUPS, "generators": list(GENERATORS), "candidate_groups": 1000, "split_image_counts": {"train": 64, "validation": 64, "test": 192}, "selection_created_at_utc": datetime.now(timezone.utc).isoformat(), "selection_before_any_detector_scores": True, "archives": archives, "expected_selected_compressed_bytes": sum(row["compressed_size"] for row in rows), "selection": rows}
        save_json(plan_path, plan)
    print(f"Frozen {len(rows)} images in {GROUPS} paired groups; payload {plan['expected_selected_compressed_bytes']:,} bytes.", flush=True)
    if args.plan_only:
        return
    for source, member, filename in (
        ("synthbuster", "synthbuster/LICENCE.txt", "Synthbuster-LICENCE.txt"),
        ("synthbuster", "synthbuster/readme.md", "Synthbuster-readme.md"),
        ("synthbuster", "synthbuster/prompts.csv", "Synthbuster-prompts.csv"),
        ("raise", "real_RAISE_1k/RAISE_License.pdf", "RAISE_License.pdf"),
        ("raise", "real_RAISE_1k/README.txt", "RAISE-README.txt"),
    ):
        target = metadata_dir / filename
        if not target.exists():
            target.write_bytes(read_member(client, archives[source], indexes[source][member]))

    def acquire(row):
        target = root / row["path"]
        blob = target.read_bytes() if target.exists() else read_member(client, archives[row["source"]], row)
        if len(blob) != row["file_size"] or zlib.crc32(blob) & 0xFFFFFFFF != row["crc32"]:
            raise ValueError("Existing image or retrieved member does not match its frozen ZIP identity.")
        with Image.open(io.BytesIO(blob)) as image:
            width, height, image_format, mode = image.width, image.height, image.format, image.mode
            image.verify()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp = target.with_suffix(".partial")
            temp.write_bytes(blob)
            temp.replace(target)
        license_text = "CC BY-NC-SA 4.0; see metadata/Synthbuster-LICENCE.txt" if row["source"] == "synthbuster" else "RAISE non-commercial research and educational use; see metadata/RAISE_License.pdf"
        return {**row, "sha256": digest(blob), "license": license_text, "width": width, "height": height, "bytes": len(blob), "format": image_format, "mode": mode}

    completed, failures = [], []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        tasks = {pool.submit(acquire, row): row for row in rows}
        for task in as_completed(tasks):
            row = tasks[task]
            try:
                completed.append(task.result())
            except Exception as exc:
                failures.append({"source_id": row["source_id"], "error": f"{type(exc).__name__}: {exc}"})
            if (len(completed) + len(failures)) % 20 == 0:
                print(f"Acquired {len(completed)}/{len(rows)}; failures {len(failures)}; transferred {client.received_bytes:,} bytes.", flush=True)
    status = {"completed_at_utc": datetime.now(timezone.utc).isoformat(), "images": len(completed), "failures": failures, "received_bytes_this_run": client.received_bytes, "requested_bytes_this_run": client.requested_bytes, "selection_plan_sha256": digest(plan_path.read_bytes()), "script_sha256": digest(Path(__file__).read_bytes()), "no_scores_computed": True}
    save_json(metadata_dir / "acquisition-status.json", status)
    if failures:
        raise RuntimeError(f"{len(failures)} selected images failed; no substitutions made. Rerun to resume.")
    by_id = {row["source_id"]: row for row in completed}
    fields = ["source_id", "path", "label", "generator", "group_id", "split", "sha256", "source_url", "archive_member", "paired_generator", "license", "width", "height", "bytes", "format", "mode", "source", "origin_page", "source_preprocessing", "crc32"]
    manifest = root / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(by_id[row["source_id"]] for row in rows)
    status["manifest_sha256"] = digest(manifest.read_bytes())
    save_json(metadata_dir / "acquisition-status.json", status)
    print(f"Complete: {manifest}; SHA256 {status['manifest_sha256']}", flush=True)


if __name__ == "__main__":
    main()
