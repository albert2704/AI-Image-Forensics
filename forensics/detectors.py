"""Optional research-model adapters. Missing models never produce substitute scores.

B-Free estimates whole-image AI generation evidence; TruFor estimates local
manipulation evidence. These quantities must not be merged or relabelled.
"""

from __future__ import annotations

import hashlib
from contextlib import redirect_stdout
import importlib.util
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid


BFREE_REVIEWED_REVISION = "c6a9f898782fb466b29af01f21960b67415afb0e"
TRUFOR_REVIEWED_REVISION = "ae54475df6f41a491d7615100feb19263dec13f7"


class DetectorUnavailableError(RuntimeError):
    """A requested detector is not installed, configured, or operational."""


class UnavailableDetector:
    available = False
    status = "unavailable"

    def __init__(self, reason: str = "B-Free repository and weights are not configured.", name: str = "B-Free"):
        self.name = name
        self.reason = reason

    def detect(self, image_path: Path) -> dict:
        raise DetectorUnavailableError(self.reason)


def _revision(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        revision = result.stdout.strip()
        return revision if re.fullmatch(r"[0-9a-f]{40,64}", revision) else None
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_module(name: str, path: Path, package: bool = False):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None,
    )
    if spec is None or spec.loader is None:
        raise DetectorUnavailableError(f"Cannot import model source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


class BFreeDetector:
    """Load the official B-Free model once, retaining its native preprocessing.

    ``repo`` can be the repository root or its ``code`` directory. ``weights``
    can be the BFREE_dino2reg4 directory or its parent weights directory.
    """

    name = "B-Free"
    reason = ""
    status = "configured"
    available = True

    def __init__(self, repo: str, weights: str | None = None, device: str = "cpu"):
        self.repo = Path(repo).expanduser().resolve()
        self.code_dir = self.repo / "code" if (self.repo / "code" / "networks").is_dir() else self.repo
        if not (self.code_dir / "networks" / "__init__.py").is_file():
            raise DetectorUnavailableError(f"B-Free source not found under {self.repo}")
        self.weights_dir = Path(weights).expanduser().resolve() if weights else self.code_dir / "weights" / "BFREE_dino2reg4"
        if not (self.weights_dir / "config.yaml").is_file():
            nested = self.weights_dir / "BFREE_dino2reg4"
            if (nested / "config.yaml").is_file():
                self.weights_dir = nested
            else:
                raise DetectorUnavailableError(f"B-Free config.yaml not found under {self.weights_dir}")
        try:
            import yaml
            with (self.weights_dir / "config.yaml").open(encoding="utf-8") as handle:
                self._config = yaml.safe_load(handle)
            if not isinstance(self._config, dict) or not all(isinstance(self._config.get(key), str) for key in ("weights_file", "arch", "norm_type")):
                raise ValueError("B-Free config requires weights_file, arch, and norm_type strings.")
            self._checkpoint = (self.weights_dir / self._config["weights_file"]).resolve()
            if not self._checkpoint.is_relative_to(self.weights_dir.resolve()) or not self._checkpoint.is_file():
                raise ValueError("B-Free checkpoint is missing or is outside its weights directory.")
        except Exception as exc:
            raise DetectorUnavailableError(f"B-Free checkpoint configuration is unavailable: {exc}") from exc
        if not re.fullmatch(r"cpu|mps|cuda(?::\d+)?", device):
            raise ValueError("B-Free device must be cpu, mps, cuda, or cuda:N.")
        self.device = device
        self.model_revision = _revision(self.code_dir)
        self._lock = threading.Lock()
        self._model = None
        self._transform = None
        self._checkpoint_sha256 = None

    def _load(self):
        if self._model is not None:
            return
        try:
            import torch
            from torchvision.transforms import Compose

            config = self._config
            checkpoint = self._checkpoint
            if self.device.startswith("cuda") and not torch.cuda.is_available():
                raise ValueError("CUDA was requested but is not available.")
            if self.device == "mps" and not torch.backends.mps.is_available():
                raise ValueError("MPS was requested but is not available.")
            # Unique package names avoid collisions with other projects' utils/networks.
            suffix = hashlib.sha256(str(self.code_dir).encode()).hexdigest()[:12]
            networks = _load_module(f"_forensics_bfree_networks_{suffix}", self.code_dir / "networks" / "__init__.py", package=True)
            normalization = _load_module(f"_forensics_bfree_norm_{suffix}", self.code_dir / "utils" / "normalization.py")
            with redirect_stdout(sys.stderr):
                model = networks.load_weights(networks.get_network(config["arch"]), str(checkpoint))
                transform = Compose(normalization.get_list_norm(config["norm_type"]))
            self._model = model.to(self.device).eval()
            self._transform = transform
            self._checkpoint_sha256 = _sha256(checkpoint)
            self.status = "ready"
        except Exception as exc:
            self._model = None
            self.status = "error"
            self.reason = f"B-Free could not load: {exc}"
            raise DetectorUnavailableError(self.reason) from exc

    def detect(self, image_path: Path) -> dict:
        started = time.perf_counter()
        with self._lock:
            self._load()
            import torch
            from PIL import Image

            with Image.open(image_path) as original:
                image = original.convert("RGB")
            # DINOv2 uses 14-pixel patch embeddings; below that no embedding exists.
            if min(image.size) < 14:
                raise ValueError("B-Free requires both image dimensions to be at least 14 pixels.")
            with torch.inference_mode():
                tensor = self._transform(image).unsqueeze(0).to(self.device)
                output = self._model(tensor).detach().cpu()
            if tuple(output.shape) == (1, 1):
                raw_logit = float(output[0, 0])
            elif tuple(output.shape) == (1, 2):
                raw_logit = float(output[0, 1] - output[0, 0])
            else:
                raise ValueError(f"Unexpected B-Free output shape: {tuple(output.shape)}")
            if not math.isfinite(raw_logit):
                raise ValueError("B-Free returned a non-finite logit.")
            score = 1 / (1 + math.exp(-raw_logit)) if raw_logit >= 0 else math.exp(raw_logit) / (1 + math.exp(raw_logit))
            return {
                "score": score, "raw_logit": raw_logit,
                "score_kind": "ai_generation", "model": self.name,
                "model_revision": self.model_revision,
                "checkpoint_sha256": self._checkpoint_sha256,
                "device": self.device, "runtime_seconds": time.perf_counter() - started,
                "calibrated_probability": False,
            }


def choose_detector(config: dict | None = None):
    """Select the real adapter or an explicit unavailable state, never a heuristic."""
    config = config or {}
    def setting(name, short, default=None):
        return config.get(name, config.get(short, os.environ.get(name, default)))
    repo = setting("BFREE_REPO", "repo")
    if not repo:
        return UnavailableDetector("Set BFREE_REPO and install the official B-Free checkpoint to enable AI scoring.")
    missing = [name for name in ("torch", "torchvision", "timm", "yaml", "PIL") if importlib.util.find_spec(name) is None]
    if missing:
        return UnavailableDetector("B-Free dependencies missing: " + ", ".join(missing) + ". See docs/MODEL_SETUP.md.")
    try:
        return BFreeDetector(str(repo), setting("BFREE_WEIGHTS", "weights"), str(setting("BFREE_DEVICE", "device", "cpu")))
    except (OSError, ValueError, DetectorUnavailableError) as exc:
        return UnavailableDetector(str(exc))


def run_trufor(image_path, output_dir, repo, python_executable, device="cpu") -> dict:
    """Run the official TruFor CLI and validate its actual outputs before rendering.

    Output paths are absolute. An isolated run directory prevents the upstream
    skip-existing-output behavior from silently reusing an older image's result.
    """
    import numpy as np
    from PIL import Image

    source = Path(image_path).expanduser().resolve(strict=True)
    root = Path(repo).expanduser().resolve(strict=True)
    code_dir = root / "TruFor_train_test" if (root / "TruFor_train_test" / "test.py").is_file() else root
    entry = code_dir / "test.py"
    checkpoint = code_dir / "pretrained_models" / "trufor.pth.tar"
    if not entry.is_file() or not checkpoint.is_file():
        raise DetectorUnavailableError("TruFor needs TruFor_train_test/test.py and pretrained_models/trufor.pth.tar. See docs/MODEL_SETUP.md.")
    if device == "cpu":
        gpu = "-1"
    elif re.fullmatch(r"cuda(?::\d+)?", device):
        gpu = device.partition(":")[2] or "0"
    else:
        raise ValueError("Official TruFor supports cpu or cuda:N; MPS is not exposed by its CLI.")
    executable = shutil.which(str(python_executable))
    if executable is None:
        raise DetectorUnavailableError("The configured TruFor Python executable does not exist.")
    with Image.open(source) as image:
        width, height = image.size
    run_dir = Path(output_dir).expanduser().resolve() / ("trufor-" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "result.npz"
    command = [executable, str(entry), "-g", gpu, "-in", str(source), "-out", str(result_path), "-exp", "trufor_ph3", "TEST.MODEL_FILE", str(checkpoint)]
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=code_dir, capture_output=True, text=True, timeout=600, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DetectorUnavailableError("TruFor exceeded the 10-minute inference limit.") from exc
    (run_dir / "inference.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0 or not result_path.is_file():
        raise DetectorUnavailableError(f"TruFor produced no usable result. See {run_dir.name}/inference.log in the run directory.")
    with np.load(result_path, allow_pickle=False) as output:
        required = {"map", "conf", "score", "imgsize"}
        if not required.issubset(output.files):
            raise ValueError("TruFor output is missing localization, confidence, score, or dimensions.")
        anomaly = np.array(output["map"])
        confidence = np.array(output["conf"])
        score_array = np.array(output["score"])
        size = np.array(output["imgsize"])
    if size.shape != (2,) or not np.array_equal(size, [height, width]):
        raise ValueError("TruFor output dimensions do not match the input image.")
    for name, array in (("map", anomaly), ("conf", confidence)):
        if array.shape != (height, width) or array.dtype.kind not in "fiu" or not np.isfinite(array).all():
            raise ValueError(f"Invalid TruFor {name} dimensions or values.")
        if np.any(array < 0) or np.any(array > 1):
            raise ValueError(f"TruFor {name} must be in [0, 1].")
    if score_array.size != 1 or score_array.dtype.kind not in "fiu":
        raise ValueError("TruFor score must be a numeric scalar.")
    score = float(score_array.reshape(-1)[0])
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("TruFor score must be finite and in [0, 1].")
    # Fixed colour range, no per-image contrast stretching or invented hotspots.
    stops = np.array([[30, 58, 138], [8, 145, 178], [250, 204, 21], [220, 38, 38]])
    positions = np.linspace(0, 1, len(stops))
    rgb = np.stack([np.interp(anomaly, positions, stops[:, channel]) for channel in range(3)], axis=-1)
    heatmap_path = run_dir / "localization-heatmap.png"
    reliability_path = run_dir / "localization-reliability.png"
    overlay_path = run_dir / "localization-overlay.png"
    heatmap_image = Image.fromarray(rgb.round().astype(np.uint8))
    heatmap_image.save(heatmap_path)
    Image.fromarray((confidence * 255).round().astype(np.uint8)).save(reliability_path)
    with Image.open(source) as original:
        Image.blend(original.convert("RGB"), heatmap_image, 0.38).save(overlay_path)
    return {
        "status": "complete",
        "message": "TruFor generated a manipulation anomaly map and localization reliability map. Output dimensions and numeric ranges were checked.",
        "warnings": ["TruFor localizes manipulation anomalies; it does not identify AI-generated pixels.", "The displayed score is not an independently calibrated probability."],
        "model": "TruFor", "score": score, "score_kind": "local_manipulation",
        "input_sha256": _sha256(source), "input_name": source.name,
        "calibrated_probability": False, "model_revision": _revision(code_dir),
        "checkpoint_sha256": _sha256(checkpoint), "device": device,
        "heatmap_path": str(heatmap_path), "reliability_path": str(reliability_path),
        "overlay_path": str(overlay_path),
        "npz_path": str(result_path), "imgsize": [height, width],
        "runtime_seconds": time.perf_counter() - started,
        "heatmap_kind": "local_manipulation_anomaly", "heatmap_range": [0, 1],
        "heatmap_legend": "Fixed scale: blue 0 → cyan → yellow → red 1; higher values indicate stronger manipulation anomalies.",
        "reliability_legend": "Black 0 → white 1; lighter pixels indicate greater estimated localization reliability.",
        "reliability_mean": float(confidence.mean()),
    }


REGIONAL_PATH_KEYS = ("heatmap_path", "reliability_path", "overlay_path", "npz_path")


def publish_regional(result: dict, directory, run_id: str, prefix: str) -> dict:
    """Copy regional PNGs into the run directory and return a record with no local paths.

    The adapter returns absolute paths for its own use. A served report only
    needs the URLs, so the paths stop here.
    """
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
