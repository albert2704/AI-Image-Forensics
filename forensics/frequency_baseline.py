"""A fixed, interpretable FFT/DCT baseline for controlled comparison with B-Free.

This is a supervised comparator, not a substitute score when B-Free is missing.
Only training images may be passed to ``fit_model``. Its sigmoid outputs are
uncalibrated classifier scores, and are not probabilities of an image's origin.
NumPy implements the features and optimizer; Pillow only decodes/resizes images.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

import numpy as np
from PIL import Image


FEATURE_SPEC = {
    "version": 1,
    "feature_count": 79,
    "resize": {"width": 256, "height": 256, "filter": "Pillow LANCZOS", "preserve_aspect_ratio": False},
    "decode": "Pillow convert RGB; no EXIF transpose, ICC conversion, or alpha compositing; use normalized pipeline images",
    "luminance": {"rgb_weights": [0.299, 0.587, 0.114], "rgb_divisor": 255.0, "dtype": "float64"},
    "fft": {
        "features": 16,
        "input": "luminance minus its image mean",
        "normalization": "orthonormal 2D FFT",
        "power": "squared complex magnitude",
        "aggregation": "mean log1p(power) within each annulus, excluding the DC coefficient",
        "annuli": "16 equal-width radial frequency bins from 0 to sqrt(0.5**2 + 0.5**2) cycles/pixel; upper endpoint included",
        "ordering": "increasing radial frequency",
    },
    "dct": {
        "features": 63,
        "blocks": "non-overlapping 8x8 luminance blocks, aligned to the top-left",
        "transform": "orthonormal DCT-II on each axis",
        "aggregation": "mean absolute magnitude of each coefficient over all 1024 blocks",
        "ordering": "row-major frequency (u,v), excluding DC (0,0), after the 16 FFT features",
    },
}

TRAINING_SPEC = {
    "version": 1,
    "classifier": "binary L2 logistic regression, positive label 1 is AI-generated",
    "standardization": "training mean and population standard deviation (ddof=0) only; scales <= 1e-12 replaced by 1",
    "objective": "mean(logaddexp(0, logit) - y*logit) + 0.5*l2*sum(weights**2); intercept unpenalized",
    "l2": 0.01,
    "optimizer": "deterministic Newton method with Armijo backtracking",
    "initialization": "zero weights; intercept log(training positive fraction / negative fraction)",
    "max_iterations": 100,
    "gradient_inf_tolerance": 1e-8,
    "armijo_constant": 1e-4,
    "backtracking_factor": 0.5,
    "max_backtracking_steps": 40,
    "nonconvergence": "raise an error; never silently export an unconverged model",
    "tuning": "none; fixed features, regularization, and stopping rule",
    "calibrated_probability": False,
}

_FEATURE_COUNT = 79
_MODEL_VERSION = 1


def _canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _preprocess_sha256() -> str:
    # Hash the implementation as well as its declared specification. This is
    # deliberately conservative: changing this module invalidates saved models.
    return hashlib.sha256(_canonical_bytes(FEATURE_SPEC) + b"\n" + Path(__file__).read_bytes()).hexdigest()


def _dct_blocks(luminance: np.ndarray) -> np.ndarray:
    """Return orthonormal 8x8 DCT-II coefficients, shape (block_y, block_x, 8, 8)."""
    matrix = np.sqrt(2.0 / 8.0) * np.cos(np.pi * np.arange(8)[:, None] * (np.arange(8) + 0.5) / 8.0)
    matrix[0] /= np.sqrt(2.0)
    height, width = luminance.shape
    blocks = luminance.reshape(height // 8, 8, width // 8, 8).transpose(0, 2, 1, 3)
    return matrix @ blocks @ matrix.T


def extract_features(image_or_path) -> np.ndarray:
    """Extract 16 radial FFT and 63 block-DCT features from a Pillow image/path.

    Image input is not mutated. Every image is converted to RGB and resized to
    256x256 before luminance conversion, including non-square and smaller inputs.
    """
    if isinstance(image_or_path, Image.Image):
        rgb = image_or_path.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS)
    else:
        with Image.open(image_or_path) as image:
            rgb = image.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS)
    pixels = np.asarray(rgb, dtype=np.float64) / 255.0
    luminance = pixels @ np.array([0.299, 0.587, 0.114], dtype=np.float64)
    spectrum = np.fft.fft2(luminance - luminance.mean(), norm="ortho")
    log_power = np.log1p(np.abs(spectrum) ** 2)
    frequencies = np.fft.fftfreq(256)
    radius = np.hypot(frequencies[:, None], frequencies[None, :])
    bin_index = np.minimum((radius / np.sqrt(0.5) * 16).astype(int), 15)
    non_dc = radius > 0
    counts = np.bincount(bin_index[non_dc], minlength=16)
    fft_features = np.bincount(bin_index[non_dc], weights=log_power[non_dc], minlength=16) / counts
    dct_features = np.abs(_dct_blocks(luminance)).mean(axis=(0, 1)).reshape(-1)[1:]
    features = np.concatenate((fft_features, dct_features))
    if features.shape != (_FEATURE_COUNT,) or not np.isfinite(features).all():
        raise ValueError("Feature extraction produced invalid or non-finite features.")
    return features


def _numeric_array(value, name: str) -> np.ndarray:
    try:
        raw = np.asarray(value)
        if raw.dtype.kind not in "biuf":
            raise ValueError(f"{name} must contain real numeric values.")
        array = raw.astype(np.float64)
    except (TypeError, OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must contain real numeric values.") from exc
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite values.")
    return array


def _feature_matrix(value) -> np.ndarray:
    array = _numeric_array(value, "X")
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] != _FEATURE_COUNT:
        raise ValueError(f"X must be a nonempty 2D matrix with {_FEATURE_COUNT} features per image.")
    return array


def _source_ids(value, count: int) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError("training_source_ids must have one ID per training image.")
    ids = list(value)
    if any(not isinstance(item, str) or not item or item != item.strip() for item in ids):
        raise ValueError("Training source IDs must be nonempty strings without surrounding whitespace.")
    if len(set(ids)) != len(ids):
        raise ValueError("Training source IDs must be unique; do not train on repeated source variants.")
    return ids


def _protocol_hash(value) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("protocol_hash must be a lowercase SHA-256 hexadecimal digest.")
    return value


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    result = np.empty_like(logits, dtype=np.float64)
    positive = logits >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
    negative_exp = np.exp(logits[~positive])
    result[~positive] = negative_exp / (1.0 + negative_exp)
    return result


def fit_model(X, y, training_source_ids, protocol_hash) -> dict:
    """Fit this preregistered baseline using only the supplied training samples.

    IDs are retained in sample order for split audits. No data splitting,
    validation-based selection, hyperparameter search, or score calibration occurs.
    """
    features = _feature_matrix(X)
    labels = _numeric_array(y, "y")
    if labels.shape != (len(features),) or not np.isin(labels, [0.0, 1.0]).all():
        raise ValueError("y must have one binary 0/1 label per training image.")
    if len(np.unique(labels)) != 2:
        raise ValueError("Training requires both label classes (0 and 1).")
    source_ids = _source_ids(training_source_ids, len(features))
    protocol = _protocol_hash(protocol_hash)
    with np.errstate(over="ignore", invalid="ignore"):
        mean = features.mean(axis=0)
        scale = features.std(axis=0, ddof=0)
        scale[scale <= 1e-12] = 1.0
        standardized = (features - mean) / scale
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.isfinite(standardized).all():
        raise ValueError("Training feature magnitudes are too large for finite standardization.")

    design = np.column_stack((standardized, np.ones(len(features))))
    parameters = np.zeros(_FEATURE_COUNT + 1, dtype=np.float64)
    positive_fraction = labels.mean()
    parameters[-1] = np.log(positive_fraction / (1.0 - positive_fraction))
    penalty = np.full(_FEATURE_COUNT + 1, TRAINING_SPEC["l2"], dtype=np.float64)
    penalty[-1] = 0.0

    def objective(candidate):
        logits = design @ candidate
        return float(np.mean(np.logaddexp(0.0, logits) - labels * logits) + 0.5 * np.dot(penalty * candidate, candidate))

    updates = 0
    for _ in range(TRAINING_SPEC["max_iterations"] + 1):
        probabilities = _sigmoid(design @ parameters)
        gradient = design.T @ (probabilities - labels) / len(labels) + penalty * parameters
        gradient_norm = float(np.max(np.abs(gradient)))
        if gradient_norm <= TRAINING_SPEC["gradient_inf_tolerance"]:
            break
        if updates == TRAINING_SPEC["max_iterations"]:
            raise ValueError("Frequency baseline optimizer did not converge within its fixed iteration budget.")
        curvature = probabilities * (1.0 - probabilities)
        hessian = (design.T * curvature) @ design / len(labels) + np.diag(penalty)
        try:
            direction = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Frequency baseline Newton system is singular.") from exc
        directional_derivative = float(gradient @ direction)
        if not np.isfinite(direction).all() or directional_derivative <= 0:
            raise ValueError("Frequency baseline optimizer produced an invalid descent direction.")
        current_objective = objective(parameters)
        step = 1.0
        for _ in range(TRAINING_SPEC["max_backtracking_steps"]):
            candidate = parameters - step * direction
            candidate_objective = objective(candidate)
            if np.isfinite(candidate_objective) and candidate_objective <= current_objective - TRAINING_SPEC["armijo_constant"] * step * directional_derivative:
                parameters = candidate
                break
            step *= TRAINING_SPEC["backtracking_factor"]
        else:
            raise ValueError("Frequency baseline line search failed; no model was exported.")
        updates += 1

    return {
        "model_version": _MODEL_VERSION,
        "model_type": "frequency",
        "feature_spec": json.loads(_canonical_bytes(FEATURE_SPEC)),
        "training_spec": json.loads(_canonical_bytes(TRAINING_SPEC)),
        "preprocess_sha256": _preprocess_sha256(),
        "scaler": {"mean": mean.tolist(), "scale": scale.tolist()},
        "weights": parameters[:-1].tolist(),
        "intercept": float(parameters[-1]),
        "training_source_ids": source_ids,
        "protocol_hash": protocol,
        "training_diagnostics": {
            "converged": True,
            "iterations": updates,
            "gradient_inf_norm": gradient_norm,
            "penalized_mean_loss": objective(parameters),
            "sample_count": len(labels),
        },
    }


def _model_arrays(model: dict):
    if not isinstance(model, dict) or model.get("model_version") != _MODEL_VERSION or model.get("model_type") != "frequency":
        raise ValueError("Unsupported frequency baseline model format.")
    if model.get("feature_spec") != FEATURE_SPEC or model.get("training_spec") != TRAINING_SPEC:
        raise ValueError("Model feature/training specifications do not match this implementation.")
    if model.get("preprocess_sha256") != _preprocess_sha256():
        raise ValueError("Model preprocessing fingerprint does not match this implementation.")
    _protocol_hash(model.get("protocol_hash"))
    ids = model.get("training_source_ids")
    if not isinstance(ids, list) or len(ids) < 2:
        raise ValueError("Model must record its training source IDs.")
    _source_ids(ids, len(ids))
    try:
        mean = _numeric_array(model["scaler"]["mean"], "scaler.mean")
        scale = _numeric_array(model["scaler"]["scale"], "scaler.scale")
        weights = _numeric_array(model["weights"], "weights")
        intercept = _numeric_array(model["intercept"], "intercept")
    except (KeyError, TypeError) as exc:
        raise ValueError("Model is missing its scaler or classifier parameters.") from exc
    if any(array.shape != (_FEATURE_COUNT,) for array in (mean, scale, weights)) or intercept.shape != ():
        raise ValueError("Model scaler and weights must have 79 elements and intercept must be scalar.")
    if np.any(scale <= 0):
        raise ValueError("Model scaler scales must be positive.")
    diagnostics = model.get("training_diagnostics", {})
    if not isinstance(diagnostics, dict) or diagnostics.get("converged") is not True or diagnostics.get("sample_count") != len(ids):
        raise ValueError("Model must record successful convergence and the training sample count.")
    return mean, scale, weights, float(intercept)


def _predict_logits(model: dict, X) -> np.ndarray:
    features = _feature_matrix(X)
    mean, scale, weights, intercept = _model_arrays(model)
    with np.errstate(over="ignore", invalid="ignore"):
        logits = ((features - mean) / scale) @ weights + intercept
    if not np.isfinite(logits).all():
        raise ValueError("Prediction produced non-finite logits.")
    return logits


def predict_scores(model: dict, X) -> np.ndarray:
    """Score using the frozen training scaler; never refit on prediction samples."""
    return _sigmoid(_predict_logits(model, X))


def save_model(model: dict, path) -> None:
    """Atomically create a JSON model, refusing to overwrite an existing artifact."""
    _model_arrays(model)
    payload = json.dumps(model, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".frequency-model-", suffix=".tmp", dir=destination.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Linking is atomic and fails if the destination exists; os.replace would
        # silently clobber a previously frozen checkpoint.
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _decode_model(payload: bytes) -> dict:
    try:
        model = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Frequency model must be a UTF-8 JSON document.") from exc
    _model_arrays(model)
    return model


def load_model(path) -> dict:
    """Load and validate a JSON model; never deserialize executable pickle data."""
    return _decode_model(Path(path).read_bytes())


class FrequencyDetector:
    """Pipeline-compatible adapter for an explicitly trained frequency baseline."""

    name = "Frequency baseline (FFT + DCT)"
    available = True
    status = "ready"
    reason = ""

    def __init__(self, model_path):
        self.model_path = Path(model_path).expanduser().resolve(strict=True)
        payload = self.model_path.read_bytes()
        self.model = _decode_model(payload)
        self.fingerprint = {
            "model_type": "frequency",
            "checkpoint_sha256": hashlib.sha256(payload).hexdigest(),
            "preprocess_sha256": self.model["preprocess_sha256"],
            "protocol_hash": self.model["protocol_hash"],
            "training_source_ids": list(self.model["training_source_ids"]),
        }

    def detect(self, image_path) -> dict:
        started = time.perf_counter()
        logits = _predict_logits(self.model, extract_features(image_path)[None, :])
        fingerprint = json.loads(_canonical_bytes(self.fingerprint))
        return {
            "score": float(_sigmoid(logits)[0]),
            "raw_logit": float(logits[0]),
            "score_kind": "ai_generation",
            "model": self.name,
            "device": "cpu",
            "calibrated_probability": False,
            "runtime_seconds": time.perf_counter() - started,
            "model_fingerprint": fingerprint,
            **fingerprint,
        }
