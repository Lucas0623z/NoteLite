"""Server-local V2 update; no credential or runtime file enters source output."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import time

STAGED = Path(os.environ["NOTELITE_AI_RELEASE"])
TRANSFER = Path(os.environ["NOTELITE_AI_TRANSFER_ROOT"])
TARGET = Path("/opt/notelite-accounts")
PRIVATE = Path("/var/lib/notelite-accounts")
DROPIN = Path("/etc/systemd/system/notelite-accounts.service.d/analysis.conf")
BACKUP = Path("/root/notelite-ai-upgrades") / time.strftime("%Y%m%dT%H%M%S")
BACKUP.mkdir(mode=0o700, parents=True, exist_ok=False)
identity = pwd.getpwnam("audiveris")
saved = {}


def run(args, timeout=90):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise RuntimeError("ai_update_step_failed:" + Path(args[0]).name)
    return result.stdout


def replace(path, raw, mode=0o644, service_owner=False):
    assert not path.is_symlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path not in saved:
        saved[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.is_file() else None
        if path.is_file():
            dest = BACKUP / str(path).lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(saved[path][0]); dest.chmod(0o600)
    fd, temp = tempfile.mkstemp(prefix=".notelite-v2-", dir=path.parent)
    with os.fdopen(fd, "wb") as out:
        out.write(raw); out.flush(); os.fsync(out.fileno())
    os.chmod(temp, mode)
    if service_owner: os.chown(temp, identity.pw_uid, identity.pw_gid)
    os.replace(temp, path)


def source_offer():
    run(["bash", str(STAGED / "source-offer.sh")], 90)


try:
    assert (TARGET / ".notelite-managed").is_file()
    assert PRIVATE.is_dir() and not PRIVATE.is_symlink() and PRIVATE.stat().st_mode & 0o077 == 0
    assert TRANSFER.parent == Path("/root/notelite-ai-transfers") and not TRANSFER.is_symlink()
    key_ready = TRANSFER / "key.ready"
    assert key_ready.is_file() and not key_ready.is_symlink() and key_ready.stat().st_mode & 0o077 == 0
    manifest = json.loads((STAGED / "accounts/manifest.json").read_text())
    assert manifest["practice_analysis.py"] == "e7220d7af2abe927c58323d64b2c04e53bdc03a22c4e576b10165d3fa1dd0802"
    assert {n for n in manifest if n.startswith("contracts/")} == {"contracts/practice-record-analysis/aggregate-input.schema.json","contracts/practice-record-analysis/output.schema.json"}
    for name, expected in manifest.items():
        source = STAGED / "accounts" / name
        assert source.is_file() and not source.is_symlink() and source.resolve().is_relative_to((STAGED / "accounts").resolve())
        raw = source.read_bytes(); assert hashlib.sha256(raw).hexdigest() == expected
        replace(TARGET / name, raw, 0o755 if name.endswith(".sh") else 0o644)
        parent = (TARGET / name).parent
        while parent != TARGET:
            parent.chmod(0o755); parent = parent.parent
    replace(TARGET / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    assets_manifest = json.loads((STAGED / "private-assets/manifest.json").read_text())
    assert len(assets_manifest) == 8
    private_assets = PRIVATE / "practice-record-analysis"
    assert not private_assets.is_symlink()
    private_assets.mkdir(mode=0o700,exist_ok=True)
    os.chown(private_assets,identity.pw_uid,identity.pw_gid);private_assets.chmod(0o700)
    for name,expected in assets_manifest.items():
        assert Path(name).name==name
        source=STAGED / "private-assets" / name
        assert source.is_file() and not source.is_symlink()
        raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
        replace(private_assets / name,raw,0o600,True)
    gateway = Path("/opt/notelite-gateway")
    gw_manifest = json.loads((STAGED / "gateway/manifest.json").read_text())
    render = (STAGED / "gateway/deploy/render_nginx.py").read_bytes()
    assert hashlib.sha256(render).hexdigest() == gw_manifest["deploy/render_nginx.py"]
    replace(gateway / "deploy/render_nginx.py", render)
    replace(gateway / "manifest.json", (json.dumps(gw_manifest,indent=2)+"\n").encode())
    site = Path("/etc/nginx/sites-available/notelite-omr-gateway.conf")
    assert site.read_text().startswith("# Managed by NoteLite OMR gateway deployment v1\n")
    replace(site, run(["python3",str(gateway / "deploy/render_nginx.py"),"--stage","https","--accounts"]))
    run(["nginx", "-t"])
    replace(PRIVATE / "deepseek-key", key_ready.read_bytes(), 0o600, True)
    replace(DROPIN, (STAGED / "accounts/deploy/notelite-accounts-ai.conf").read_bytes())
    DROPIN.parent.chmod(0o755)
    run(["python3", "-m", "compileall", "-q", str(TARGET / "practice_analysis.py"), str(TARGET / "account_service.py")])
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "restart", "notelite-accounts.service"])
    run(["systemctl", "reload", "nginx.service"])
    for _ in range(30):
        try:
            health = json.loads(run(["curl", "--fail", "--silent", "--show-error", "--max-time", "5", "https://124.221.211.156/api/account/health"]))
            assert health["omrOwnershipHook"] is True
            break
        except (RuntimeError, AssertionError): time.sleep(.5)
    else: raise RuntimeError("v2_account_health_not_ready")
    for unit in ("notelite-accounts.service", "notelite-gateway.service", "notelite-omr.service", "nginx.service"):
        run(["systemctl", "is-active", "--quiet", unit])
    run(["/opt/notelite-gateway/deploy/check-health.sh"])
    # Health does not imply a real model call. The external acceptance performs
    # exactly one synthetic request after this successful source publication.
    source_offer()
    key = PRIVATE / "deepseek-key"
    assert key.stat().st_uid == identity.pw_uid and key.stat().st_mode & 0o777 == 0o600
    print(json.dumps({"status":"passed", "version":"practice-facts-v2", "sourceSha256":manifest["practice_analysis.py"],
                      "privateCredentialMode":"0600", "credentialLogged":False, "privateSkillFiles":8,
                      "customOperatorAssetsPublic":False,
                      "model":"deepseek-flash", "realModelRequestVerified":False, "backup":str(BACKUP)}))
except BaseException:
    for path, old in saved.items():
        if old is not None:
            path.write_bytes(old[0]); path.chmod(old[1])
            if path == PRIVATE / "deepseek-key": os.chown(path, identity.pw_uid, identity.pw_gid)
        elif path == DROPIN:
            path.unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["systemctl", "restart", "notelite-accounts.service"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["nginx", "-t"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["systemctl", "reload", "nginx.service"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try: source_offer()
    except Exception: pass
    print("ROLLBACK: account sources and service configuration restored; runtime history preserved")
    raise
