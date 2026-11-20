"""Cross-platform behaviour: study-directory locking and served content types."""

import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from forensics.benchmark import _run_lock
from forensics.server import content_type


@contextmanager
def temporary_module(name, value):
    """Import `name` as `value` for the duration of the block; None hides it."""
    previous = sys.modules.get(name, ...)
    sys.modules[name] = value
    try:
        yield
    finally:
        if previous is ...:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


class ContentTypeTests(unittest.TestCase):
    def test_static_types_do_not_depend_on_the_host_registry(self):
        expected = {
            "app.js": "text/javascript; charset=utf-8",
            "guide.js": "text/javascript; charset=utf-8",
            "style.css": "text/css; charset=utf-8",
            "index.html": "text/html; charset=utf-8",
            "report.json": "application/json; charset=utf-8",
            "overlay.png": "image/png",
            "overlay.jpg": "image/jpeg",
            "map.svg": "image/svg+xml",
        }
        for name, kind in expected.items():
            self.assertEqual(content_type(Path("web") / name), kind, name)

    def test_unknown_extension_never_yields_an_empty_type(self):
        self.assertEqual(content_type(Path("noext")), "application/octet-stream")
        self.assertEqual(content_type(Path("strange.zzz")), "application/octet-stream")


class RunLockTests(unittest.TestCase):
    def test_lock_is_exclusive_and_released(self):
        with TemporaryDirectory() as tmp:
            with _run_lock(tmp):
                with self.assertRaises(RuntimeError):
                    with _run_lock(tmp):
                        pass
            with _run_lock(tmp):
                pass

    def test_windows_path_uses_msvcrt_when_fcntl_is_absent(self):
        calls = []
        fake = types.SimpleNamespace(
            LK_NBLCK=1,
            LK_UNLCK=2,
            locking=lambda fd, mode, size: calls.append((mode, size)),
        )
        with TemporaryDirectory() as tmp, temporary_module("fcntl", None), temporary_module("msvcrt", fake):
            with _run_lock(tmp):
                self.assertEqual(calls, [(fake.LK_NBLCK, 1)])
        self.assertEqual(calls, [(fake.LK_NBLCK, 1), (fake.LK_UNLCK, 1)])

    def test_windows_path_reports_a_second_writer(self):
        def locking(fd, mode, size):
            if mode == 1:
                raise OSError("locked")

        fake = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
        with TemporaryDirectory() as tmp, temporary_module("fcntl", None), temporary_module("msvcrt", fake):
            with self.assertRaises(RuntimeError):
                with _run_lock(tmp):
                    pass


if __name__ == "__main__":
    unittest.main()
