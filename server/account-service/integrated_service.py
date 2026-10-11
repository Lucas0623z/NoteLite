#!/usr/bin/env python3
"""Production account launcher with private OMR/legacy adapters enabled."""
import argparse
from pathlib import Path
import re
import signal
import sys
import threading

import account_service
from omr_bridge import OMRBridge


class IntegratedStore(account_service.Store):
    def course_detail(self, db, user_id, course_id):
        course = self.get_course(db, user_id, course_id)
        if course["creator"] != user_id:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            for score in db.execute("SELECT * FROM course_scores WHERE course_id=? ORDER BY id", (course_id,)).fetchall():
                if not db.execute("SELECT 1 FROM course_deliveries WHERE course_id=? AND user_id=? AND course_score_id=?",
                                  (course_id, user_id, score["id"])).fetchone():
                    delivered = self.insert_score(db, user_id, score["title"], score["xml"])
                    db.execute("INSERT INTO course_deliveries VALUES(?,?,?,?)", (course_id, user_id, score["id"], delivered["id"]))
        result = super().course_detail(db, user_id, course_id)
        result["deliveredScores"] = [{**self.score_meta(row), "courseScoreId": row["course_score_id"]}
                                     for row in db.execute("SELECT s.*,d.course_score_id FROM scores s JOIN course_deliveries d ON d.score_id=s.id WHERE d.course_id=? AND d.user_id=? ORDER BY s.id",
                                                           (course_id, user_id))]
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--internal-key-file", required=True, type=Path)
    parser.add_argument("--gateway-root", type=Path, default=Path("/var/lib/notelite-gateway"))
    parser.add_argument("--gateway-code", type=Path, default=Path("/opt/notelite-gateway"))
    parser.add_argument("--upstream-port", type=int, default=8765)
    parser.add_argument("--upstream-token-file", type=Path, default=Path("/var/lib/audiveris/access-token"))
    parser.add_argument("--max-recording-mb", type=int, default=100)
    parser.add_argument("--recording-quota-mb", type=int, default=1024)
    parser.add_argument("--disk-reserve-mb", type=int, default=256)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.upstream_port <= 65535:
        parser.error("端口无效。")
    if not 1 <= args.max_recording_mb <= 1024 or not args.max_recording_mb <= args.recording_quota_mb <= 102400 or not 64 <= args.disk_reserve_mb <= 102400:
        parser.error("录音限额无效。")
    if args.internal_key_file.is_symlink() or args.upstream_token_file.is_symlink() or args.gateway_code.is_symlink():
        parser.error("私有凭据或网关源码路径不能是符号链接。")
    key = args.internal_key_file.read_text(encoding="ascii").strip()
    token = args.upstream_token_file.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        parser.error("私有服务凭据格式无效。")
    sys.path.insert(0, str(args.gateway_code))
    import gateway
    gateway_store = gateway.Store(args.gateway_root)
    bridge = OMRBridge(gateway_store, token, args.public_origin, upstream_port=args.upstream_port)
    store = IntegratedStore(args.root, omr_import=bridge.import_score, legacy_claim=bridge.claim,
                                  max_recording=args.max_recording_mb * 1024 ** 2,
                                  recording_quota=args.recording_quota_mb * 1024 ** 2,
                                  disk_reserve=args.disk_reserve_mb * 1024 ** 2)
    def account_user_exists(owner):
        with store.connect() as db:
            return db.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone() is not None
    bridge.account_user_exists = account_user_exists
    server = account_service.Server(("127.0.0.1", args.port), store, args.public_origin, key)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop);signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
