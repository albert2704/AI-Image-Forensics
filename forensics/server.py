"""Loopback-only local application server. No image leaves this machine."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import mimetypes
import os
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple

from .pipeline import MAX_BYTES, analyze, write_exports, decode_image
from .detectors import choose_detector, run_trufor
from .regional import publish_regional
from .agent import investigate, validate_agent_config, save_investigation
from .planner import LocalPlanner

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "output" / "runs"
EXAMPLE_ROOT = ROOT / "output" / "model-verification"
WORK_LOCK = threading.Lock()
JOBS = {}
JOBS_LOCK = threading.Lock()


class ExampleUnavailable(RuntimeError):
    """The committed demo run is missing or its pointer is unreadable."""


class RunLocation(NamedTuple):
    directory: Path
    writable: bool


def run_location(run_id):
    """Resolve a run directory. Only output/runs is writable; committed artifacts are read-only."""
    local = RUNS / run_id
    if local.is_dir():
        return RunLocation(local, True)
    committed = EXAMPLE_ROOT / run_id
    if committed.is_dir():
        return RunLocation(committed, False)
    return None


def load_example():
    pointer = ROOT / "output" / "verified-example.json"
    if not pointer.is_file():
        raise ExampleUnavailable("The recorded example is not installed.")
    try:
        run_id = json.loads(pointer.read_text()).get("run_id")
    except (ValueError, AttributeError):
        raise ExampleUnavailable("The recorded example pointer is invalid.") from None
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ExampleUnavailable("The recorded example pointer is invalid.")
    location = run_location(run_id)
    if location is None:
        raise ExampleUnavailable("The recorded example is not installed.")
    report_path = location.directory / "report.json"
    source_path = location.directory / "source.bin"
    if not report_path.is_file() or not source_path.is_file():
        raise ExampleUnavailable("The recorded example is not installed.")
    report = json.loads(report_path.read_text())
    return {"report": report, "filename": report["image"]["name"],
            "image_base64": base64.b64encode(source_path.read_bytes()).decode("ascii")}


def trufor_status():
    repo = os.environ.get("TRUFOR_REPO", "")
    root = Path(repo).expanduser() if repo else None
    configured = bool(root and ((root / "TruFor_train_test" / "test.py").is_file() or (root / "test.py").is_file()))
    return {"available": configured, "reason": "Configured; model dependencies and weights are checked when scanning." if configured else "Set TRUFOR_REPO and install its pretrained model to enable regional evidence."}


class Handler(BaseHTTPRequestHandler):
    detector = None
    planner = None

    def send_json(self, obj, status=200):
        data = json.dumps(obj, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed:
            self.send_json({"error": "Only the local application address is accepted."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in allowed}:
            self.send_json({"error": "Cross-origin requests are not accepted."}, 403)
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            return self.send_json({"bfree": {"available": self.detector.available, "reason": self.detector.reason}, "trufor": trufor_status(), "planner": self.planner.status()})
        if re.fullmatch(r"/api/investigations/[a-f0-9]{32}", path):
            run_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(run_id)
                snapshot = job["report"] if job else None
            if snapshot is not None:
                return self.send_json(snapshot)
            saved = RUNS / run_id / "investigation.json"
            if saved.is_file():
                report = json.loads(saved.read_text())
                if report.get("status") == "running":
                    report.update(status="error", current_step="Server stopped before this investigation completed.")
                return self.send_json(report)
            return self.send_json({"error": "Investigation not found."}, 404)
        if path == "/api/example":
            try:
                return self.send_json(load_example())
            except ExampleUnavailable as exc:
                return self.send_json({"error": str(exc)}, 404)
        if path.startswith("/runs/"):
            if not re.fullmatch(r"/runs/[a-f0-9]{32}/[A-Za-z0-9_.-]+", path):
                return self.send_json({"error": "Not found"}, 404)
            run_id, filename = path.removeprefix("/runs/").split("/", 1)
            if Path(filename).suffix not in {".png", ".jpg", ".json", ".csv"}:
                return self.send_json({"error": "Not found"}, 404)
            location = run_location(run_id)
            if location is None:
                return self.send_json({"error": "Not found"}, 404)
            file = location.directory / filename
        elif path in {"/", "/index.html", "/style.css", "/app.js", "/rules.js", "/guide.js"}:
            file = ROOT / "web" / ("index.html" if path == "/" else path.lstrip("/"))
        else:
            return self.send_json({"error": "Not found"}, 404)
        if not file.is_file():
            return self.send_json({"error": "Not found"}, 404)
        content = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(file))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if not self.local_request():
            return
        if self.path not in {"/api/analyze", "/api/regional", "/api/investigate"} and not re.fullmatch(r"/api/investigations/[a-f0-9]{32}/cancel", self.path):
            return self.send_json({"error": "Not found"}, 404)
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self.send_json({"error": "Expected JSON."}, 415)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= int(MAX_BYTES * 1.4) + 10000:
                return self.send_json({"error": "Request exceeds upload limit."}, 413)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
        except (ValueError, UnicodeError):
            return self.send_json({"error": "Invalid request body."}, 400)
        if self.path.endswith("/cancel"):
            run_id = self.path.split("/")[-2]
            with JOBS_LOCK:
                job = JOBS.get(run_id)
                if job:
                    job["cancel"].set()
            return self.send_json({"status": "cancel_requested", "message": "Stops after the current model call finishes."} if job else {"error": "Active investigation not found."}, 200 if job else 404)
        if self.path == "/api/investigate":
            try:
                return self.start_investigation(payload)
            except (ValueError, binascii.Error) as exc:
                return self.send_json({"error": str(exc)}, 400)
        if not WORK_LOCK.acquire(blocking=False):
            return self.send_json({"error": "An analysis is already running. Please wait for it to finish."}, 409)
        try:
            if self.path == "/api/analyze":
                raw = payload.get("image_base64", "")
                if not isinstance(raw, str):
                    raise ValueError("Image must be a base64 string.")
                data = base64.b64decode(raw, validate=True)
                report = analyze(data, str(payload.get("filename", "image")), payload, RUNS, self.detector)
                return self.send_json(report)
            return self.regional(payload)
        except (ValueError, binascii.Error) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": f"Analysis failed: {type(exc).__name__}: {exc}"}, 500)
        finally:
            WORK_LOCK.release()

    def start_investigation(self, payload):
        if payload.get("threshold", .5) != .5:
            raise ValueError("The adaptive investigation uses a fixed 0.5 threshold. Remove the threshold field or set it to 0.5.")
        config = validate_agent_config(payload)
        raw = payload.get("image_base64", "")
        if not isinstance(raw, str):
            raise ValueError("Image must be a base64 string.")
        data = base64.b64decode(raw, validate=True)
        decode_image(data)  # Reject malformed uploads before acknowledging a job.
        if not self.planner.status()["available"]:
            return self.send_json({"error": self.planner.status()["reason"]}, 503)
        if not self.detector.available:
            return self.send_json({"error": self.detector.reason}, 503)
        if not WORK_LOCK.acquire(blocking=False):
            return self.send_json({"error": "Another analysis is already running."}, 409)
        run_id = uuid.uuid4().hex
        cancel = threading.Event()
        initial = {"run_id": run_id, "status": "running", "current_step": "Preparing image", "observations": [], "decisions": [], "model_tool_calls": 0, "planner_calls": 0, "config": config}
        with JOBS_LOCK:
            for old_id in list(JOBS):
                if len(JOBS) < 50:
                    break
                if JOBS[old_id]["report"].get("status") != "running":
                    del JOBS[old_id]
            JOBS[run_id] = {"report": initial, "cancel": cancel}

        def progress(report):
            with JOBS_LOCK:
                JOBS[run_id]["report"] = report

        def work():
            try:
                investigate(data, str(payload.get("filename", "image")), config, RUNS,
                            self.detector, self.planner, run_id=run_id, progress=progress, cancelled=cancel.is_set)
            except Exception as exc:
                with JOBS_LOCK:
                    report = dict(JOBS[run_id]["report"])
                report.update(status="error", current_step="Investigation failed", error=f"{type(exc).__name__}: {exc}")
                if (RUNS / run_id).is_dir():
                    save_investigation(report, RUNS / run_id)
                progress(report)
            finally:
                WORK_LOCK.release()

        threading.Thread(target=work, name=f"investigation-{run_id}", daemon=True).start()
        return self.send_json({"run_id": run_id, "status": "running", "status_url": f"/api/investigations/{run_id}"}, 202)

    def regional(self, payload):
        run_id = str(payload.get("run_id", ""))
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid analysis ID.")
        location = run_location(run_id)
        if location is None or not (location.directory / "report.json").is_file():
            return self.send_json({"error": "Analysis not found."}, 404)
        if not location.writable:
            return self.send_json({"error": "The recorded example is read-only. Analyze your own image to run a regional scan."}, 409)
        directory = location.directory
        report = json.loads((directory / "report.json").read_text())
        if not trufor_status()["available"]:
            result = {"status": "unavailable", "message": trufor_status()["reason"], "warnings": []}
            report["regional"] = result
            write_exports(report, directory)
            return self.send_json(result)
        try:
            result = run_trufor(directory / "original.png", directory,
                                os.environ["TRUFOR_REPO"],
                                os.environ.get("TRUFOR_PYTHON", "python3"),
                                os.environ.get("TRUFOR_DEVICE", "cpu"))
        except Exception as exc:
            detail = str(exc).replace(str(directory), "the run directory")
            result = {"status": "error", "message": f"Regional inference failed: {type(exc).__name__}: {detail}",
                      "warnings": ["No valid regional evidence was produced."]}
            report["regional"] = result
            write_exports(report, directory)
            return self.send_json(result)
        report["regional"] = publish_regional(result, directory, run_id, "regional-")
        write_exports(report, directory)
        return self.send_json(report["regional"])


def main():
    parser = argparse.ArgumentParser(description="Run the local AI Image Forensics Assistant")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.detector = choose_detector({})
    Handler.planner = LocalPlanner()
    RUNS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"AI Image Forensics Assistant: http://127.0.0.1:{args.port}", flush=True)
    print(f"B-Free: {Handler.detector.status}. {Handler.detector.reason}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
