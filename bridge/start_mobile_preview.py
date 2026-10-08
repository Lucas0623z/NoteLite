#!/usr/bin/env python3
"""Run the mobile interface and the real OMR worker on loopback for development."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading

from notelite_bridge import BridgeServer, JavaEngine, JobService


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=root / "app/build/install/app")
    parser.add_argument("--java", default="java")
    parser.add_argument("--node", default="node")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--worker-port", type=int, default=8765)
    args = parser.parse_args()
    interface = root / "mobile-ui"
    vite = interface / "node_modules/vite/bin/vite.js"
    node = shutil.which(args.node)
    if node is None or not vite.is_file():
        parser.error("Install the mobile-ui dependencies first (npm ci), and make Node.js available.")
    if not 1024 <= args.port <= 65535 or not 1024 <= args.worker_port <= 65535 or args.port == args.worker_port:
        parser.error("Choose two different nonprivileged ports.")
    engine = JavaEngine(args.distribution, args.java, "4g")
    # A fresh credential is shared only by this worker and the local development proxy.
    token = secrets.token_urlsafe(32)
    service = JobService(root / "bridge/.mobile-preview-jobs", token, engine.command)
    server = BridgeServer(("127.0.0.1", args.worker_port), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = dict(os.environ, NOTELITE_BRIDGE_TOKEN=token,
                       NOTELITE_BRIDGE_ORIGIN=f"http://127.0.0.1:{args.worker_port}")
    child = None
    try:
        child = subprocess.Popen([node, str(vite), "--host", "127.0.0.1", "--port", str(args.port), "--strictPort"],
                                 cwd=interface, env=environment)
        print(f"Mobile preview: http://127.0.0.1:{args.port}", flush=True)
        print("OMR runs on this computer. No microphone audio leaves the device. Press Ctrl+C to stop.", flush=True)
        return child.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
