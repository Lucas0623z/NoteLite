"""TEST FIXTURE ONLY: deterministic subprocess stand-in; performs no music recognition."""

from pathlib import Path
import sys
import time

output = Path(sys.argv[sys.argv.index("-output") + 1])
source = Path(sys.argv[-1])
body = source.read_bytes()
if b"SLOW" in body:
    time.sleep(0.6)
if b"TIMEOUT" in body:
    time.sleep(5)
if b"FAIL" in body:
    print("Fixture engine failure")
    raise SystemExit(7)
if b"NO_EXPORT" in body:
    raise SystemExit(0)
nested = output / "book"
nested.mkdir(parents=True, exist_ok=True)
(nested / "score.musicxml").write_bytes(b'<score-partwise version="4.0"/>')
(nested / "score.mid").write_bytes(b"MThd fixture")
(nested / "score.omr").write_bytes(b"OMR fixture")
(nested / "private.txt").write_bytes(b"not an artifact")
