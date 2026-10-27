import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from forensics.frequency_baseline import (
    FEATURE_SPEC, TRAINING_SPEC, FrequencyDetector, _dct_blocks,
    extract_features, fit_model, load_model, predict_scores, save_model,
)


PROTOCOL_HASH = hashlib.sha256(b"unit-test-only protocol; no benchmark data").hexdigest()


def training_fixture():
    rng = np.random.default_rng(42)
    X = rng.normal(0, 0.03, size=(40, 79))
    y = np.repeat([0, 1], 20)
    X[:, 0] += 2 * y - 1
    X[:, 1] = 7.0  # Exact constant feature exercises zero-variance handling.
    return X, y, [f"unit-source-{index:02d}" for index in range(len(y))]


class FrequencyFeatureTests(unittest.TestCase):
    def test_constants_are_finite_and_have_no_spurious_frequency_energy(self):
        for level in (0, 127, 255):
            with self.subTest(level=level):
                image = Image.new("RGB", (43, 71), (level, level, level))
                features = extract_features(image)
                self.assertEqual(features.shape, (79,))
                self.assertEqual(features.dtype, np.float64)
                self.assertTrue(np.isfinite(features).all())
                np.testing.assert_allclose(features, 0, atol=1e-14)
                self.assertEqual(image.size, (43, 71))

    def test_texture_differs_from_constant_and_paths_match_image_input(self):
        rng = np.random.default_rng(7)
        image = Image.fromarray(rng.integers(0, 256, (256, 256, 3), dtype=np.uint8))
        texture = extract_features(image)
        self.assertGreater(float(np.linalg.norm(texture)), 0.1)
        self.assertTrue(np.all(texture >= 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "texture.png"
            image.save(path)
            np.testing.assert_array_equal(texture, extract_features(path))

    def test_known_orthonormal_dct_basis_and_energy(self):
        u, v = 2, 5
        coordinates = np.arange(8) + 0.5
        basis_u = np.sqrt(2 / 8) * np.cos(np.pi * u * coordinates / 8)
        basis_v = np.sqrt(2 / 8) * np.cos(np.pi * v * coordinates / 8)
        block = np.outer(basis_u, basis_v)
        coefficients = _dct_blocks(np.tile(block, (2, 3)))
        expected = np.zeros((2, 3, 8, 8))
        expected[:, :, u, v] = 1
        np.testing.assert_allclose(coefficients, expected, atol=2e-15)
        self.assertAlmostEqual(float(np.sum(coefficients[0, 0] ** 2)), float(np.sum(block ** 2)), places=14)

    def test_known_fft_frequency_occupies_expected_radial_bin(self):
        row = np.tile(np.array([0, 0, 255, 255], dtype=np.uint8), 64)
        gray = np.tile(row, (256, 1))
        features = extract_features(Image.fromarray(gray, "L"))
        expected_bin = int(0.25 / np.sqrt(0.5) * 16)
        self.assertEqual(int(np.argmax(features[:16])), expected_bin)
        self.assertGreater(features[expected_bin], 0)
        np.testing.assert_allclose(np.delete(features[:16], expected_bin), 0, atol=1e-20)


class FrequencyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.X, cls.y, cls.ids = training_fixture()
        cls.model = fit_model(cls.X, cls.y, cls.ids, PROTOCOL_HASH)

    def test_known_signal_learns_and_training_records_convergence(self):
        scores = predict_scores(self.model, self.X)
        self.assertTrue(np.all(scores[self.y == 0] < 0.1))
        self.assertTrue(np.all(scores[self.y == 1] > 0.9))
        self.assertTrue(self.model["training_diagnostics"]["converged"])
        self.assertLessEqual(self.model["training_diagnostics"]["gradient_inf_norm"], TRAINING_SPEC["gradient_inf_tolerance"])
        self.assertEqual(self.model["training_source_ids"], self.ids)
        self.assertEqual(self.model["protocol_hash"], PROTOCOL_HASH)
        self.assertEqual(self.model["feature_spec"], FEATURE_SPEC)

    def test_scaler_uses_training_only_and_prediction_is_batch_independent(self):
        np.testing.assert_allclose(self.model["scaler"]["mean"], self.X.mean(axis=0), rtol=0, atol=0)
        expected_scale = self.X.std(axis=0, ddof=0)
        expected_scale[expected_scale <= 1e-12] = 1
        np.testing.assert_array_equal(self.model["scaler"]["scale"], expected_scale)
        before = json.dumps(self.model, sort_keys=True, allow_nan=False)
        single = predict_scores(self.model, self.X[:1])
        mixed = predict_scores(self.model, np.vstack((self.X[:1], np.full((1, 79), 1000.0))))
        self.assertAlmostEqual(single[0], mixed[0], places=14)
        self.assertEqual(before, json.dumps(self.model, sort_keys=True, allow_nan=False))

    def test_repeated_fits_are_identical_and_do_not_mutate_inputs(self):
        X_before, y_before, ids_before = self.X.copy(), self.y.copy(), list(self.ids)
        again = fit_model(self.X, self.y, self.ids, PROTOCOL_HASH)
        self.assertEqual(self.model, again)
        np.testing.assert_array_equal(X_before, self.X)
        np.testing.assert_array_equal(y_before, self.y)
        self.assertEqual(ids_before, self.ids)

    def test_intercept_handles_imbalanced_constant_features(self):
        model = fit_model(np.ones((10, 79)), np.array([0] * 8 + [1] * 2), [f"constant-{i}" for i in range(10)], PROTOCOL_HASH)
        np.testing.assert_allclose(predict_scores(model, np.ones((2, 79))), 0.2, atol=1e-12)
        np.testing.assert_array_equal(model["weights"], np.zeros(79))

    def test_serialization_adapter_and_file_fingerprint_are_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            image_path = Path(directory) / "image.png"
            Image.new("RGB", (96, 80), (50, 100, 200)).save(image_path)
            save_model(self.model, path)
            loaded = load_model(path)
            self.assertEqual(self.model, loaded)
            adapter = FrequencyDetector(path)
            result = adapter.detect(image_path)
            expected = predict_scores(loaded, extract_features(image_path)[None, :])[0]
            self.assertAlmostEqual(expected, result["score"], places=15)
            self.assertFalse(result["calibrated_probability"])
            self.assertEqual(result["score_kind"], "ai_generation")
            self.assertEqual(adapter.fingerprint["checkpoint_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(adapter.fingerprint["training_source_ids"], self.ids)
            self.assertEqual(adapter.fingerprint["protocol_hash"], PROTOCOL_HASH)
            self.assertEqual(result["model_fingerprint"], adapter.fingerprint)
            self.assertTrue(adapter.available)
            self.assertEqual(adapter.status, "ready")
            self.assertTrue(np.isfinite(result["raw_logit"]))
            self.assertEqual(len(adapter.fingerprint["preprocess_sha256"]), 64)

    def test_save_refuses_overwrite_and_leaves_no_temporary_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            save_model(self.model, path)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                save_model(self.model, path)
            self.assertEqual(original, path.read_bytes())
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["model.json"])

    def test_rejects_invalid_features_labels_ids_and_protocol(self):
        cases = [
            (self.X[:, :-1], self.y, self.ids, PROTOCOL_HASH),
            (self.X[0], self.y, self.ids, PROTOCOL_HASH),
            (np.empty((0, 79)), [], [], PROTOCOL_HASH),
            (np.full_like(self.X, np.nan), self.y, self.ids, PROTOCOL_HASH),
            (np.full_like(self.X, np.inf), self.y, self.ids, PROTOCOL_HASH),
            (self.X.astype(str), self.y, self.ids, PROTOCOL_HASH),
            (self.X, self.y[:-1], self.ids, PROTOCOL_HASH),
            (self.X, np.full_like(self.y, 2), self.ids, PROTOCOL_HASH),
            (self.X, np.zeros_like(self.y), self.ids, PROTOCOL_HASH),
            (self.X, np.full(len(self.y), 0.5), self.ids, PROTOCOL_HASH),
            (self.X, np.full(len(self.y), np.nan), self.ids, PROTOCOL_HASH),
            (self.X, self.y, self.ids[:-1], PROTOCOL_HASH),
            (self.X, self.y, ["same"] * len(self.ids), PROTOCOL_HASH),
            (self.X, self.y, [""] + self.ids[1:], PROTOCOL_HASH),
            (self.X, self.y, [" padded"] + self.ids[1:], PROTOCOL_HASH),
            (self.X, self.y, self.ids, "not-a-protocol-hash"),
        ]
        for index, arguments in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                fit_model(*arguments)
        for features in (np.full((1, 79), np.nan), self.X[0], self.X[:, :-1]):
            with self.subTest(predict_shape=features.shape), self.assertRaises(ValueError):
                predict_scores(self.model, features)

    def test_load_rejects_tampered_scaler_spec_and_implementation(self):
        modifications = [
            ("preprocess_sha256", "0" * 64),
            ("feature_spec", {}),
            ("weights", [float("nan")] * 79),
            ("scaler", {"mean": [0] * 79, "scale": [0] * 79}),
            ("intercept", [0]),
            ("training_diagnostics", {"converged": False, "sample_count": len(self.ids)}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-model.json"
            for key, value in modifications:
                model = copy.deepcopy(self.model)
                model[key] = value
                path.write_text(json.dumps(model), encoding="utf-8")
                with self.subTest(field=key), self.assertRaises(ValueError):
                    load_model(path)


if __name__ == "__main__":
    unittest.main()
