#!/usr/bin/env python3
"""Run a real image -> HTTP job -> MusicXML/MIDI smoke check (requires built Java app)."""

import argparse
import io
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

from notelite_bridge import BridgeServer, JavaEngine, JobService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=Path("app/build/install/app"))
    parser.add_argument("--java", default="java")
    parser.add_argument("--sample", type=Path, default=Path("data/examples/chula.png"))
    args = parser.parse_args()
    engine = JavaEngine(args.distribution, args.java, "4g")
    token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="notelite-smoke-") as directory:
        service = JobService(Path(directory), token, engine.command, timeout=180)
        server = BridgeServer(("127.0.0.1", 0), service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        def request(path, data=None, method=None):
            req = Request(origin + path, data=data, method=method,
                          headers={"Authorization": "Bearer " + token})
            with urlopen(req, timeout=30) as response:
                return response.read()

        try:
            assert json.loads(request("/v1/health"))["status"] == "ok"
            upload_path = "/v1/jobs?" + urlencode({"filename": args.sample.name})
            job = json.loads(request(upload_path, args.sample.read_bytes(), "POST"))
            job_path = "/v1/jobs/" + job["id"]
            deadline = time.monotonic() + 195
            while job["state"] in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.25)
                job = json.loads(request(job_path))
            if job["state"] != "succeeded":
                engine_log = Path(directory) / job["id"] / "engine.log"
                if engine_log.exists():
                    print(engine_log.read_text(encoding="utf-8", errors="replace")[-12000:])
                raise RuntimeError(f"Recognition did not succeed: {job['state']}: {job['error']}")
            formats = set()
            for artifact in job["artifacts"]:
                payload = request(artifact["path"])
                extension = Path(artifact["name"]).suffix
                if extension == ".mxl":
                    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                        container = ET.fromstring(archive.read("META-INF/container.xml"))
                        rootfiles = [node.attrib["full-path"] for node in container.iter()
                                     if node.tag.rsplit("}", 1)[-1] == "rootfile"]
                        assert rootfiles, "MusicXML container has no root score"
                        score = ET.fromstring(archive.read(rootfiles[0]))
                        assert score.tag == "score-partwise" and score.find("part") is not None
                    formats.add("MusicXML")
                elif extension == ".mid":
                    assert payload[:4] == b"MThd" and b"MTrk" in payload
                    formats.add("MIDI")
                print(f"Downloaded {artifact['name']}: {len(payload)} bytes")
            assert formats == {"MusicXML", "MIDI"}, f"Missing export format: {formats}"
            request(job_path, method="DELETE")
            print("PASS: real HTTP upload, OMR recognition, MusicXML/MIDI download and cleanup")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            service.close()


if __name__ == "__main__":
    main()
