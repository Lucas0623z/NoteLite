#!/usr/bin/env python3
"""Authenticated HTTP adapter for the real NoteLite batch engine (Python 3.10+)."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import uuid
import zipfile


MAX_UPLOAD = 25 * 1024 * 1024
INPUT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SCORE_EXTENSIONS = {".mxl", ".musicxml", ".xml"}
ARTIFACT_EXTENSIONS = SCORE_EXTENSIONS | {".omr", ".mid", ".midi"}
LOG = logging.getLogger("notelite.bridge")


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


def validate_filename(filename: str) -> str:
    if (not filename or len(filename) > 255 or filename in {".", ".."}
            or any(c in filename for c in "/\\")
            or any(ord(c) < 32 or ord(c) == 127 for c in filename)):
        raise APIError(400, "A plain filename without directory components is required.")
    extension = Path(filename).suffix.lower()
    if extension not in INPUT_EXTENSIONS:
        raise APIError(415, "Supported files: PDF, PNG, JPEG, TIFF.")
    return extension


def valid_signature(extension: str, header: bytes) -> bool:
    if extension == ".pdf":
        return header.startswith(b"%PDF-")
    if extension == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    return header.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"))


class JavaEngine:
    """Use an installDist build, including native libraries for this host platform."""

    def __init__(self, distribution: Path, java: str, heap: str):
        self.distribution = distribution.resolve(strict=True)
        library = self.distribution / "lib"
        app_jar = library / "notelite.jar"
        if not library.is_dir() or not app_jar.is_file():
            raise ValueError("Distribution must contain lib/notelite.jar; run :app:installDist first.")
        with zipfile.ZipFile(app_jar) as archive:
            if "NoteLite.class" not in archive.namelist():
                raise ValueError("lib/notelite.jar does not contain the NoteLite main class.")
        executable = shutil.which(java)
        if executable is None or Path(executable).suffix.lower() in {".bat", ".cmd"}:
            raise ValueError("--java must identify the Java executable, not a shell script.")
        self.java = str(Path(executable).resolve())
        version = subprocess.run([self.java, "-version"], capture_output=True, text=True,
                                 timeout=15, check=False)
        if version.returncode != 0 or not re.search(r'version "21(?:[.\"+\-])',
                                                   version.stdout + version.stderr):
            raise ValueError("Use JDK 21: this project enables Java 21 preview features.")
        if not re.fullmatch(r"[1-9][0-9]*[mMgG]", heap):
            raise ValueError("--heap must be a size such as 4g or 2048m.")
        self.heap = heap

    def command(self, source: Path, output: Path) -> list[str]:
        return [self.java, f"-Xmx{self.heap}", "--enable-preview",
                "--add-exports=java.desktop/sun.awt.image=ALL-UNNAMED",
                "--enable-native-access=ALL-UNNAMED", "-Djava.awt.headless=true",
                "-Dfile.encoding=UTF-8", "-Djava.util.PropertyResourceBundle.encoding=UTF-8",
                "-cp", str(self.distribution / "lib" / "*"), "NoteLite",
                "-batch", "-transcribe", "-export", "-export-midi", "-output", str(output), "--", str(source)]


class JobService:
    def __init__(self, storage: Path, token: str, command_builder, *, queue_size: int = 4,
                 timeout: float = 600, max_jobs: int = 100, max_upload: int = MAX_UPLOAD):
        if len(token) < 32 or any(c.isspace() for c in token) or not token.isascii():
            raise ValueError("The bearer token must contain at least 32 ASCII characters without spaces.")
        if queue_size < 1 or timeout <= 0 or max_jobs < 1 or not 1 <= max_upload <= MAX_UPLOAD:
            raise ValueError("Queue, timeout and capacity limits must be positive; upload limit <= 25 MiB.")
        storage.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.storage = storage.resolve(strict=True)
        self.token = token
        self.command_builder = command_builder
        self.timeout = timeout
        self.max_upload = max_upload
        self.max_jobs = max_jobs
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.pending = queue.Queue()
        # Capacity includes uploads and the active worker, so slow uploads also reserve capacity.
        self.slots = threading.BoundedSemaphore(queue_size + 1)
        self.reserved = 0
        self.stopping = threading.Event()
        self._load_jobs()
        self.worker = threading.Thread(target=self._work, name="notelite-worker", daemon=True)
        self.worker.start()

    def _directory(self, job_id: str) -> Path:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError("Invalid job ID")
        path = self.storage / job_id
        if path.is_symlink() or path.resolve().parent != self.storage:
            raise ValueError("Unsafe job directory")
        return path

    def _save(self, job: dict) -> None:
        path = self._directory(job["id"])
        payload = {key: job[key] for key in ("id", "filename", "state", "error")}
        temporary = path / "job.json.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path / "job.json")

    def _collect(self, job_id: str) -> dict[str, Path]:
        output = self._directory(job_id) / "output"
        artifacts = {}
        if not output.is_dir() or output.is_symlink():
            return artifacts
        for path in sorted(output.rglob("*")):
            if (path.is_symlink() or not path.is_file() or path.suffix.lower() not in ARTIFACT_EXTENSIONS
                    or not path.resolve().is_relative_to(output.resolve()) or path.stat().st_size == 0):
                continue
            # A flat, unique URL-safe public name; never accept a client-provided filesystem path.
            stem = re.sub(r"[^A-Za-z0-9_.-]", "_", path.stem)[:120].strip(".") or "score"
            name = f"{len(artifacts) + 1:02d}-{stem}{path.suffix.lower()}"
            artifacts[name] = path
        return artifacts

    def _load_jobs(self) -> None:
        for path in self.storage.iterdir():
            try:
                if not path.is_dir() or path.is_symlink() or self._directory(path.name) != path:
                    continue
                metadata = path / "job.json"
                if metadata.is_symlink() or metadata.stat().st_size > 1024 * 1024:
                    continue
                job = json.loads(metadata.read_text(encoding="utf-8"))
                if job["id"] != path.name or job["state"] not in {"queued", "running", "succeeded", "failed"}:
                    continue
                validate_filename(job["filename"])
                if job["state"] in {"queued", "running"}:
                    job.update(state="failed", error="Recognition was interrupted by a service restart.")
                job["artifacts"] = self._collect(job["id"]) if job["state"] == "succeeded" else {}
                self.jobs[job["id"]] = job
                self._save(job)
            except (OSError, ValueError, KeyError, TypeError, APIError):
                LOG.warning("Ignoring an incomplete or invalid job directory: %s", path.name)

    def reserve(self) -> None:
        with self.lock:
            if self.stopping.is_set():
                raise APIError(503, "Service is stopping.")
            if len(self.jobs) + self.reserved >= self.max_jobs:
                raise APIError(503, "Job storage is full. Delete completed jobs before uploading more.")
            if not self.slots.acquire(blocking=False):
                raise APIError(503, "Recognition queue is full. Try again later.")
            self.reserved += 1

    def release_reservation(self) -> None:
        with self.lock:
            self.reserved -= 1
            self.slots.release()

    def submit(self, filename: str, body, length: int) -> dict:
        extension = validate_filename(filename)
        if not 0 < length <= self.max_upload:
            raise APIError(413, "Upload must contain between 1 byte and 25 MiB.")
        self.reserve()
        job_id = str(uuid.uuid4())
        directory = self._directory(job_id)
        committed = False
        try:
            directory.mkdir(mode=0o700)
            source = directory / f"score{extension}"
            with source.open("xb") as target:
                remaining = length
                header = b""
                while remaining:
                    chunk = body.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise APIError(400, "Upload ended before Content-Length bytes were received.")
                    header = (header + chunk)[:16]
                    target.write(chunk)
                    remaining -= len(chunk)
            if not valid_signature(extension, header):
                raise APIError(415, "File contents do not match the supplied file extension.")
            job = {"id": job_id, "filename": filename, "state": "queued", "error": None,
                   "artifacts": {}}
            with self.lock:
                if self.stopping.is_set():
                    raise APIError(503, "Service is stopping.")
                self._save(job)
                self.jobs[job_id] = job
                self.reserved -= 1
                committed = True
                response = self._public(job)
                self.pending.put((job_id, source))
                return response
        finally:
            if not committed:
                try:
                    if directory.exists():
                        shutil.rmtree(self._directory(job_id))
                except (OSError, ValueError):
                    # Preserve the upload error; an inaccessible leftover must not consume capacity.
                    LOG.exception("Could not remove rejected upload directory for job %s", job_id)
                finally:
                    self.release_reservation()

    @staticmethod
    def _public(job: dict) -> dict:
        return {key: job[key] for key in ("id", "state", "filename", "error")} | {
            "artifacts": [{"name": name, "path": f'/v1/jobs/{job["id"]}/artifacts/{name}'}
                          for name in job["artifacts"]]}

    def get(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise APIError(404, "Job not found.")
            return self._public(self.jobs[job_id])

    def open_artifact(self, job_id: str, name: str):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["state"] != "succeeded" or name not in job["artifacts"]:
                raise APIError(404, "Artifact not found.")
            path = job["artifacts"][name]
            if path.is_symlink() or not path.resolve().is_relative_to(self._directory(job_id) / "output"):
                raise APIError(404, "Artifact not found.")
            # Open under the lock so DELETE cannot race opening a file.
            try:
                return path.open("rb")
            except OSError:
                raise APIError(404, "Artifact not found.") from None

    def delete(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise APIError(404, "Job not found.")
            if job["state"] in {"queued", "running"}:
                raise APIError(409, "Wait for recognition to finish before deleting this job.")
            try:
                shutil.rmtree(self._directory(job_id))
            except OSError:
                raise APIError(409, "Job files are in use. Try deletion again later.") from None
            del self.jobs[job_id]

    def _work(self) -> None:
        while True:
            item = self.pending.get()
            if item is None:
                self.pending.task_done()
                return
            job_id, source = item
            try:
                with self.lock:
                    job = self.jobs[job_id]
                    job.update(state="running", error=None)
                    self._save(job)
                if self.stopping.is_set():
                    raise RuntimeError("Recognition was cancelled because the service is stopping.")
                output = self._directory(job_id) / "output"
                output.mkdir()
                with (self._directory(job_id) / "engine.log").open("wb") as log:
                    result = subprocess.run(self.command_builder(source, output),
                                            cwd=self._directory(job_id), stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT,
                                            timeout=self.timeout, check=False, shell=False)
                if result.returncode != 0:
                    raise RuntimeError(f"Recognition engine exited with status {result.returncode}. See server log.")
                artifacts = self._collect(job_id)
                if not any(path.suffix.lower() in SCORE_EXTENSIONS for path in artifacts.values()):
                    raise RuntimeError("No MusicXML score was produced. Check scan quality and the server log.")
                with self.lock:
                    job.update(state="succeeded", artifacts=artifacts)
            except subprocess.TimeoutExpired:
                with self.lock:
                    job.update(state="failed", error="Recognition exceeded the configured time limit.")
            except Exception as exc:
                LOG.exception("Recognition failed for job %s", job_id)
                with self.lock:
                    message = str(exc) if isinstance(exc, RuntimeError) else "Recognition failed. See server log."
                    job.update(state="failed", error=message)
            finally:
                with self.lock:
                    try:
                        self._save(job)
                    except (OSError, ValueError):
                        LOG.exception("Could not save job %s", job_id)
                    finally:
                        self.slots.release()
                self.pending.task_done()

    def close(self) -> None:
        self.stopping.set()
        self.pending.put(None)
        # Current Java subprocess has its own deadline; queued jobs are marked failed.
        self.worker.join(self.timeout + 5)


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: JobService, max_connections: int = 16):
        self.service = service
        self.connections = threading.BoundedSemaphore(max_connections)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "NoteLiteBridge/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, fmt, *args):
        # Avoid recording bearer tokens or user filenames in request logs.
        LOG.info("HTTP request from %s", self.client_address[0])

    def _json(self, status: int, value: dict | None):
        payload = b"" if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="NoteLite"')
        if status == 503:
            self.send_header("Retry-After", "5")
        self.end_headers()
        self.wfile.write(payload)

    def _dispatch(self):
        service = self.server.service
        target = urlsplit(self.path)
        if self.command == "GET" and target.path == "/v1/health":
            self._json(200, {"status": "ok"})
            return
        auth = self.headers.get_all("Authorization", [])
        supplied = auth[0].encode("utf-8") if len(auth) == 1 else b""
        if not hmac.compare_digest(supplied, ("Bearer " + service.token).encode("ascii")):
            raise APIError(401, "A valid bearer token is required.")
        if target.path == "/v1/jobs" and self.command == "POST":
            query = parse_qs(target.query, keep_blank_values=True)
            if set(query) != {"filename"} or len(query["filename"]) != 1:
                raise APIError(400, "Supply one filename query parameter.")
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
                raise APIError(400, "Use a raw request body with Content-Length and no content encoding.")
            lengths = self.headers.get_all("Content-Length", [])
            if not lengths:
                raise APIError(411, "Content-Length is required.")
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
                raise APIError(400, "Invalid Content-Length.")
            result = service.submit(query["filename"][0], self.rfile, int(lengths[0]))
            self._json(202, result)
            return
        match = re.fullmatch(r"/v1/jobs/([0-9a-f-]{36})(?:/artifacts/([A-Za-z0-9_.-]+))?", target.path)
        if not match or target.query:
            raise APIError(404, "Endpoint not found.")
        job_id, artifact_name = match.groups()
        if artifact_name is None and self.command == "GET":
            self._json(200, service.get(job_id))
        elif artifact_name is None and self.command == "DELETE":
            service.delete(job_id)
            self._json(204, None)
        elif artifact_name is not None and self.command == "GET":
            with service.open_artifact(job_id, artifact_name) as source:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(os.fstat(source.fileno()).st_size))
                self.send_header("Content-Disposition", f'attachment; filename="{artifact_name}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                shutil.copyfileobj(source, self.wfile, 64 * 1024)
        else:
            raise APIError(405, "Method not allowed.")

    def _handle(self):
        try:
            self._dispatch()
        except APIError as exc:
            self._json(exc.status, {"error": exc.message})
        except (socket.timeout, TimeoutError):
            self._json(408, {"error": "Upload timed out."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            LOG.exception("HTTP request failed")
            self._json(500, {"error": "Internal service error. See server log."})

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=Path("app/build/install/app"))
    parser.add_argument("--java", default="java", help="JDK 21 executable (java or an absolute path)")
    parser.add_argument("--heap", default="4g", help="Maximum heap for the one Java worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage", type=Path, default=Path("bridge/.notelite-bridge"))
    parser.add_argument("--token-env", default="NOTELITE_BRIDGE_TOKEN")
    parser.add_argument("--queue-size", type=int, default=4, help="Queued jobs in addition to the active job")
    parser.add_argument("--max-jobs", type=int, default=100, help="Retained jobs; delete finished jobs to free space")
    parser.add_argument("--timeout", type=float, default=600, help="Per-job Java process deadline in seconds")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        engine = JavaEngine(args.distribution, args.java, args.heap)
        service = JobService(args.storage, os.environ.get(args.token_env, ""), engine.command,
                             queue_size=args.queue_size, timeout=args.timeout, max_jobs=args.max_jobs)
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    try:
        with BridgeServer((args.host, args.port), service) as server:
            LOG.info("Listening on %s:%s; use an HTTPS reverse proxy for Apple clients", args.host, args.port)
            server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Stopping; waiting for the active recognition job to finish or time out")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
