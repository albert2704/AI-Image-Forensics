import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import unittest.mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("modal_endpoint", ROOT / "scripts" / "modal_endpoint.py")
endpoint = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = endpoint
SPEC.loader.exec_module(endpoint)

KEYS = [
    "score", "raw_logit", "score_kind", "model", "model_revision",
    "checkpoint_sha256", "device", "runtime_seconds", "calibrated_probability",
]
REVISION = "c6a9f898782fb466b29af01f21960b67415afb0e"
CHECKPOINT = "5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947"
PREDICTION = {
    "score": 0.9882320210699883,
    "raw_logit": 4.430535316467285,
    "score_kind": "ai_generation",
    "model": "B-Free",
    "model_revision": REVISION,
    "checkpoint_sha256": CHECKPOINT,
    "device": "cuda",
    "runtime_seconds": 0.28,
    "calibrated_probability": False,
}

try:
    import yaml  # noqa: F401

    HAVE_YAML = True
except ModuleNotFoundError:
    HAVE_YAML = False

STUB_YAML = types.ModuleType("yaml")
STUB_YAML.safe_load = staticmethod(lambda text: json.loads(text))


@contextlib.contextmanager
def yaml_available():
    if HAVE_YAML:
        yield
    else:
        with unittest.mock.patch.dict(sys.modules, {"yaml": STUB_YAML}):
            yield


def png_bytes(size=(32, 24)):
    stream = io.BytesIO()
    Image.new("RGB", size, "white").save(stream, format="PNG")
    return stream.getvalue()


class Chunks:
    def __init__(self, *chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class Untouchable:
    def __aiter__(self):
        raise AssertionError("the request body must not be read")


def forbidden_scorer():
    raise AssertionError("the scorer must not be built")


class FakeScorer:
    def __init__(self, prediction=None, error=None):
        self.prediction = PREDICTION if prediction is None else prediction
        self.error = error
        self.seen = []

    def detect(self, path):
        with Image.open(path) as image:
            self.seen.append((Path(path), image.format, image.size))
        if self.error is not None:
            raise self.error
        return dict(self.prediction)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)

    def request(self, **overrides):
        values = {
            "presented_secret": "s3cret",
            "content_length": None,
            "chunks": Chunks(png_bytes()),
            "expected_secret": "s3cret",
            "get_scorer": lambda: FakeScorer(),
        }
        values.update(overrides)
        return asyncio.run(endpoint.handle_score_request(**values))

    def test_module_imports_without_modal(self):
        self.assertIsNone(endpoint.modal)
        self.assertFalse(hasattr(endpoint, "app"))
        self.assertFalse(hasattr(endpoint, "image"))
        self.assertTrue(asyncio.iscoroutinefunction(endpoint.handle_score_request))
        self.assertEqual(endpoint.MAX_UPLOAD_BYTES, 20 * 1024 * 1024)
        self.assertEqual(endpoint.SECRET_HEADER, "X-BFree-Secret")
        self.assertEqual(endpoint.BFREE_CHECKPOINT_SHA256, CHECKPOINT)

    def test_missing_secret_returns_401_before_reading(self):
        reply = self.request(presented_secret=None, chunks=Untouchable(), get_scorer=forbidden_scorer)

        self.assertEqual(reply.status, 401)
        self.assertEqual(reply.body, {"error": "Unauthorized."})

    def test_wrong_secret_returns_401_before_reading(self):
        reply = self.request(presented_secret="wrong", chunks=Untouchable(), get_scorer=forbidden_scorer)

        self.assertEqual(reply.status, 401)
        self.assertEqual(reply.body, {"error": "Unauthorized."})

    def test_unset_server_secret_returns_503(self):
        for expected, presented in ((None, None), (None, ""), ("", "")):
            with self.subTest(expected=expected, presented=presented):
                reply = self.request(
                    expected_secret=expected, presented_secret=presented,
                    chunks=Untouchable(), get_scorer=forbidden_scorer,
                )
                self.assertEqual(reply.status, 503)
                self.assertEqual(reply.body, {"error": "Endpoint secret is not configured."})

    def test_declared_oversize_is_rejected_before_reading(self):
        reply = self.request(content_length=str(endpoint.MAX_UPLOAD_BYTES + 1), chunks=Untouchable(), get_scorer=forbidden_scorer)

        self.assertEqual(reply.status, 413)
        self.assertEqual(reply.body, {"error": "Image exceeds the 20 MiB limit."})

    def test_invalid_content_length_is_rejected(self):
        reply = self.request(content_length="12x", chunks=Untouchable(), get_scorer=forbidden_scorer)

        self.assertEqual(reply.status, 400)
        self.assertEqual(reply.body, {"error": "Invalid Content-Length."})

    def test_stream_oversize_stops_at_the_cap(self):
        with unittest.mock.patch.object(endpoint, "MAX_UPLOAD_BYTES", 1024):
            async def chunks():
                yield b"x" * 1025
                raise AssertionError("the endpoint read past the cap")

            reply = self.request(chunks=chunks(), get_scorer=forbidden_scorer)

        self.assertEqual(reply.status, 413)
        self.assertEqual(reply.body, {"error": "Image exceeds the 20 MiB limit."})

    def test_invalid_image_returns_400_without_a_scorer(self):
        reply = self.request(chunks=Chunks(b"not an image at all"), get_scorer=forbidden_scorer)

        self.assertEqual(reply.status, 400)
        self.assertIn("error", reply.body)
        self.assertNotIn("score", reply.body)

    def test_valid_image_returns_the_nine_keys(self):
        scorer = FakeScorer()
        reply = self.request(get_scorer=lambda: scorer)

        self.assertEqual(reply.status, 200)
        self.assertEqual(list(reply.body), KEYS)
        self.assertEqual(len(reply.body), 9)
        self.assertEqual(reply.body["model_revision"], REVISION)
        self.assertEqual(reply.body["checkpoint_sha256"], CHECKPOINT)
        self.assertEqual(scorer.seen[0][1:], ("PNG", (32, 24)))
        self.assertFalse(scorer.seen[0][0].exists())

    def test_unavailable_scorer_returns_503(self):
        scorer = FakeScorer(error=endpoint.DetectorUnavailableError("CUDA is not available"))
        reply = self.request(get_scorer=lambda: scorer)

        self.assertEqual(reply.status, 503)
        self.assertEqual(set(reply.body), {"error"})
        self.assertIn("Remote scoring is unavailable", reply.body["error"])

    def test_scorer_factory_failure_returns_503(self):
        failures = {
            "unavailable": endpoint.DetectorUnavailableError("weights are missing"),
            "broken": RuntimeError("import crashed"),
        }
        for name, error in failures.items():
            with self.subTest(name=name):
                def fail(error=error):
                    raise error

                reply = self.request(get_scorer=fail)
                self.assertEqual(reply.status, 503)
                self.assertEqual(set(reply.body), {"error"})
                self.assertIn("Remote scoring is unavailable", reply.body["error"])

    def test_scorer_failure_returns_500(self):
        scorer = FakeScorer(error=RuntimeError("grid exploded"))
        reply = self.request(get_scorer=lambda: scorer)

        self.assertEqual(reply.status, 500)
        self.assertEqual(reply.body, {"error": "Scoring failed: RuntimeError: grid exploded"})
        self.assertFalse(scorer.seen[0][0].exists())

    def test_verify_checkpoint_accepts_a_matching_checkpoint(self):
        directory, checkpoint = self.write_weights()
        digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

        with yaml_available():
            self.assertEqual(endpoint.verify_checkpoint(directory, digest), digest)

    def test_verify_checkpoint_rejects_a_mismatch(self):
        directory, _checkpoint = self.write_weights()

        with yaml_available():
            with self.assertRaises(endpoint.DetectorUnavailableError) as caught:
                endpoint.verify_checkpoint(directory, "0" * 64)

        self.assertIn("mismatch", str(caught.exception))

    def test_verify_checkpoint_rejects_an_escaping_path(self):
        directory, checkpoint = self.write_weights("../outside.pth")
        digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

        with yaml_available():
            with self.assertRaises(endpoint.DetectorUnavailableError) as caught:
                endpoint.verify_checkpoint(directory, digest)

        self.assertIn("escapes", str(caught.exception))

    def write_weights(self, weights_file="model_epoch_best.pth"):
        directory = self.temp / "BFREE_dino2reg4"
        directory.mkdir()
        config = {"weights_file": weights_file, "arch": "dino2reg4", "norm_type": "imagenet"}
        (directory / "config.yaml").write_text(json.dumps(config))
        checkpoint = directory / weights_file
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"checkpoint fixture")
        return directory, checkpoint


if __name__ == "__main__":
    unittest.main()
