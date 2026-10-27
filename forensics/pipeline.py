"""Deterministic transformations; model scores are optional, never simulated."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import platform
import time
import uuid
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, __version__ as pillow_version

MAX_BYTES = 20 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_config(config: dict) -> dict:
    out = {"quality": 90, "scale": .9, "rounds": 3, "mode": "cumulative",
           "order": "resize-jpeg", "operation": "combined", "threshold": .5}
    out.update({key: value for key, value in config.items() if key in out})
    for name, lo, hi in [("quality", 50, 100), ("rounds", 1, 5)]:
        if isinstance(out[name], bool) or not isinstance(out[name], int) or not lo <= out[name] <= hi:
            raise ValueError(f"{name} must be an integer from {lo} to {hi}.")
    for name, lo, hi in [("scale", .5, 1), ("threshold", 0, 1)]:
        if isinstance(out[name], bool) or not isinstance(out[name], (float, int)) or not math.isfinite(out[name]) or not lo <= out[name] <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}.")
    for name, options in [("mode", ["cumulative", "independent"]),
                          ("order", ["resize-jpeg", "jpeg-resize"]),
                          ("operation", ["combined", "jpeg", "resize"])]:
        if out[name] not in options:
            raise ValueError(f"Unsupported {name}.")
    return out


def decode_image(data: bytes):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Choose a nonempty image smaller than 20 MiB.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as raw:
                if raw.format not in {"JPEG", "PNG", "WEBP", "TIFF", "BMP"}:
                    raise ValueError("Use a JPEG, PNG, WebP, TIFF, or BMP image.")
                if getattr(raw, "n_frames", 1) != 1:
                    raise ValueError("Use a single-frame image.")
                fmt, raw_mode, raw_size = raw.format, raw.mode, raw.size
                image = ImageOps.exif_transpose(raw)
                notes = []
                if raw.getexif().get(274, 1) != 1:
                    notes.append("EXIF orientation was applied before processing.")
                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    bg = Image.new("RGBA", rgba.size, "white")
                    image = Image.alpha_composite(bg, rgba).convert("RGB")
                    notes.append("Transparency was composited on white before analysis.")
                else:
                    image = image.convert("RGB")
                image.load()
                if min(image.size) < 16:
                    raise ValueError("The shortest image side must be at least 16 pixels.")
                if raw_mode != "RGB":
                    notes.append(f"Source mode {raw_mode} converted to RGB; no ICC profile conversion applied.")
                return image, {"format": fmt, "source_mode": raw_mode, "source_dimensions": list(raw_size), "normalization_notes": notes}
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise ValueError("Image exceeds the 20 megapixel analysis limit.") from exc
        except (OSError, SyntaxError) as exc:
            raise ValueError("The file could not be decoded as a supported image.") from exc


def encode(image: Image.Image, fmt: str, quality: int = 90) -> bytes:
    output = io.BytesIO()
    if fmt == "JPEG":
        image.save(output, format=fmt, quality=quality, subsampling=2, optimize=False, progressive=False)
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def transform(image: Image.Image, target: tuple[int, int], config: dict):
    """Return decoded pixels, actual final file bytes and explicit operation history."""
    current = image.copy()
    steps = []
    encoded = None
    fmt = "PNG"
    order = ["resize", "jpeg"] if config["order"] == "resize-jpeg" else ["jpeg", "resize"]
    if config["operation"] != "combined":
        order = [config["operation"]]
    for operation in order:
        if operation == "resize":
            current = current.resize(target, Image.Resampling.LANCZOS)
            steps.append({"type": "resize", "width": target[0], "height": target[1], "resampler": "Pillow LANCZOS"})
            encoded, fmt = encode(current, "PNG"), "PNG"
        else:
            encoded = encode(current, "JPEG", config["quality"])
            with Image.open(io.BytesIO(encoded)) as decoded:
                current = decoded.convert("RGB")
            fmt = "JPEG"
            steps.append({"type": "jpeg", "quality": config["quality"], "subsampling": "4:2:0", "progressive": False})
    return current, encoded, fmt, steps


def distortion(original: Image.Image, variant: Image.Image):
    reference = original if original.size == variant.size else original.resize(variant.size, Image.Resampling.LANCZOS)
    error = np.asarray(reference, dtype=np.float64) - np.asarray(variant, dtype=np.float64)
    mse = float(np.mean(error ** 2))
    return mse, None if mse == 0 else float(10 * math.log10(255 ** 2 / mse))


def summarize(variants: list[dict], config: dict, detector: dict, notes: list[str]):
    warnings_out = list(notes)
    warnings_out.extend([
        "A detector score is model evidence, not a calibrated probability of authenticity.",
        "Derivatives of one image are correlated; persistence is not independent corroboration.",
        "JPEG quality is an encoder setting, not a measurement of prior compression.",
    ])
    if config["mode"] == "independent":
        warnings_out.append("Single-pass controls start from the original at each round's target size; JPEG-only controls may be identical.")
    if min(v["width"] for v in variants) < 224 or min(v["height"] for v in variants) < 224:
        warnings_out.append("At least one image has a side below 224 px. Small images and padding can alter detector behavior.")
    scored = [v["score"] for v in variants if v["score"] is not None]
    base = variants[0]["score"]
    result = {"score_min": min(scored) if scored else None, "score_max": max(scored) if scored else None,
              "flip_count": None, "warnings": warnings_out, "regional_scan_recommended": False}
    if len(scored) != len(variants) or base is None:
        result.update(title="Image measurements ready; detector evidence incomplete",
                      text="Compression and resizing were measured. No authenticity conclusion is available until a configured detector successfully scores every image.")
        if any(v["error"] for v in variants):
            warnings_out.append("One or more model runs failed. Missing values are not zero scores.")
        return result
    threshold = config["threshold"]
    flips = sum((v["score"] > threshold) != (base > threshold) for v in variants[1:])
    result["flip_count"] = flips
    result["regional_scan_recommended"] = bool(flips or any(abs(s - threshold) < .1 for s in scored) or base > threshold)
    if flips:
        title = "Detector evidence changes under processing"
        text = f"{flips} of {len(variants)-1} derivatives cross the configured {threshold:g} threshold relative to the original. Treat this image as inconclusive and inspect its provenance."
    elif base > threshold:
        title = "Elevated scores persist across these transformations"
        text = "All tested versions remain above the configured threshold. This supports consistency of the detector response, but does not prove that the image is AI-generated."
    else:
        title = "Scores stay below the configured threshold"
        text = "This detector did not raise a persistent AI-generation signal in the tested versions. Low scores do not establish that an image is authentic."
    result.update(title=title, text=text)
    return result


def write_exports(report: dict, directory: Path):
    (directory / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    fields = ["id", "round", "width", "height", "bytes", "format", "sha256", "parent_sha256", "mse", "psnr_db", "score", "raw_logit", "error", "operations"]
    with (directory / "measurements.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for variant in report["variants"]:
            writer.writerow({**variant, "operations": json.dumps(variant["operations"])})


def analyze(data: bytes, filename: str, config: dict, output_root: Path, detector) -> dict:
    config = validate_config(config)
    original, source = decode_image(data)
    started = time.perf_counter()
    run_id = uuid.uuid4().hex
    directory = output_root / run_id
    directory.mkdir(parents=True)
    (directory / "source.bin").write_bytes(data)
    detector_info = {"name": detector.name, "status": detector.status, "reason": detector.reason}
    variants = []
    last_image, parent_hash = original, None
    normalized = encode(original, "PNG")
    for index in range(config["rounds"] + 1):
        if index == 0:
            current, content, fmt, steps = original, normalized, "PNG", []
        else:
            factor = config["scale"] ** index if config["operation"] != "jpeg" else 1
            target = (max(1, round(original.width * factor)), max(1, round(original.height * factor)))
            source_image = last_image if config["mode"] == "cumulative" else original
            current, content, fmt, steps = transform(source_image, target, config)
            parent_hash = variants[-1]["sha256"] if config["mode"] == "cumulative" else variants[0]["sha256"]
        variant_id = "original" if index == 0 else f"round-{index}"
        path = directory / (variant_id + (".jpg" if fmt == "JPEG" else ".png"))
        path.write_bytes(content)
        mse, psnr = distortion(original, current)
        item = {"id": variant_id, "label": "Original (normalized)" if index == 0 else f"Round {index}",
                "round": index, "width": current.width, "height": current.height, "bytes": len(content),
                "format": fmt, "sha256": sha256(content), "parent_sha256": parent_hash, "operations": steps,
                "mse": mse, "psnr_db": psnr, "score": None, "raw_logit": None, "error": None,
                "preview_url": f"/runs/{run_id}/{path.name}"}
        if detector.available:
            try:
                prediction = detector.detect(path)
                score = float(prediction["score"])
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("Detector returned an invalid score.")
                item.update(score=score, raw_logit=prediction.get("raw_logit"), detector_evidence=prediction)
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
        variants.append(item)
        last_image = current
    if any(v["error"] for v in variants):
        detector_info["status"] = "error"
        detector_info["reason"] = "At least one inference failed; inspect per-image errors."
    report = {"schema_version": 1, "run_id": run_id,
              "image": {"name": Path(filename).name[:240], "width": original.width, "height": original.height,
                        "bytes": len(data), "sha256": sha256(data), **source},
              "config": config, "detector": detector_info, "variants": variants,
              "summary": summarize(variants, config, detector_info, source["normalization_notes"]),
              "regional": {"status": "not_requested", "message": "Optional TruFor scan evaluates manipulation anomalies, not AI origin."},
              "exports": {"json_url": f"/runs/{run_id}/report.json", "csv_url": f"/runs/{run_id}/measurements.csv"},
              "provenance": {"python": platform.python_version(), "pillow": pillow_version, "numpy": np.__version__,
                             "distortion_reference": "Original RGB resized directly to each variant's dimensions using LANCZOS.",
                             "psnr_null_meaning": "Positive infinity when mse is zero.",
                             "threshold_rule": "score > threshold", "runtime_seconds": time.perf_counter() - started}}
    write_exports(report, directory)
    return report
