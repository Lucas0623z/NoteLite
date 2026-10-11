"""Reviewed server-only install. Invoked from the checksum-verified TAT payload."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import secrets
import shutil
import subprocess
import tempfile
import time

STAGED = Path(os.environ["NOTELITE_ACCOUNT_RELEASE"])
BACKUP = Path("/root/notelite-account-upgrades") / time.strftime("%Y%m%dT%H%M%S")
BACKUP.mkdir(mode=0o700,parents=True,exist_ok=False)
SITE = Path("/etc/nginx/sites-available/notelite-omr-gateway.conf")
assert SITE.is_file() and not SITE.is_symlink()
assert SITE.read_text().startswith("# Managed by NoteLite OMR gateway deployment v1\n")
assert Path("/opt/notelite-gateway/.notelite-managed").is_file()
identity = pwd.getpwnam("audiveris")
saved = {}


def run(args, *, timeout=90):
    result = subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if result.returncode:
        raise RuntimeError("reviewed_install_step_failed:" + Path(args[0]).name)
    return result


def write(path, raw, mode=0o644):
    assert not path.is_symlink()
    path.parent.mkdir(parents=True,exist_ok=True)
    if str(path) not in saved:
        saved[str(path)] = path.read_bytes() if path.is_file() else None
        if path.is_file():
            backed = BACKUP / str(path).lstrip("/")
            backed.parent.mkdir(parents=True,exist_ok=True);backed.write_bytes(saved[str(path)])
    fd,name=tempfile.mkstemp(prefix=".notelite-account-",dir=path.parent)
    with os.fdopen(fd,"wb") as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.chmod(name,mode);os.replace(name,path)


try:
    run(["systemctl","is-active","--quiet","notelite-omr.service"])
    for part,target in (("gateway",Path("/opt/notelite-gateway")),("accounts",Path("/opt/notelite-accounts"))):
        if part=="accounts" and target.exists():
            assert (target/".notelite-managed").is_file(),"unmanaged_account_source"
        source=STAGED/part;manifest=json.loads((source/"manifest.json").read_text())
        for name,expected in manifest.items():
            path=source/name
            assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source.resolve())
            raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
            write(target/name,raw,0o755 if name.endswith(".sh") else 0o644)
        write(target/"manifest.json",(json.dumps(manifest,indent=2)+"\n").encode())
        write(target/".notelite-managed",b"NoteLite integrated account/OMR deployment v1\n")
        # TAT runs with umask 0077: source directories still need traversal by
        # the unprivileged service user. Runtime/secret directories stay 0700.
        target.chmod(0o755)
        for name in manifest:
            parent=(target/name).parent
            while parent!=target:
                assert parent.resolve().is_relative_to(target.resolve())
                parent.chmod(0o755);parent=parent.parent
    private=Path("/var/lib/notelite-accounts")
    assert not private.is_symlink();private.mkdir(mode=0o700,exist_ok=True)
    os.chown(private,identity.pw_uid,identity.pw_gid);os.chmod(private,0o700)
    key=private/"internal-key";assert not key.is_symlink()
    if not key.exists():
        descriptor=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,"w",encoding="ascii") as stream:stream.write(secrets.token_urlsafe(32)+"\n")
    os.chown(key,identity.pw_uid,identity.pw_gid);os.chmod(key,0o600)
    # Private keys are generated server-side and never included in output.
    write(Path("/etc/systemd/system/notelite-gateway.service"),(STAGED/"gateway/deploy/notelite-gateway-accounts.service").read_bytes())
    write(Path("/etc/systemd/system/notelite-accounts.service"),(STAGED/"accounts/deploy/notelite-accounts-integrated.service").read_bytes())
    site=run(["python3","/opt/notelite-gateway/deploy/render_nginx.py","--stage","https","--accounts"]).stdout
    write(SITE,site)
    run(["nginx","-t"])
    run(["systemctl","daemon-reload"])
    run(["systemctl","enable","--now","notelite-accounts.service"])
    run(["systemctl","restart","notelite-gateway.service"])
    for _ in range(20):
        try:
            run(["curl","--fail","--silent","--show-error","--max-time","5","-H","Host: 124.221.211.156","http://127.0.0.1:8771/api/account/health"])
            break
        except RuntimeError:time.sleep(.5)
    else:raise RuntimeError("account_health_not_ready")
    run(["systemctl","reload","nginx.service"])
    # nginx reload is graceful and returns before its new worker is accepting.
    for _ in range(20):
        try:
            public=json.loads(run(["curl","--fail","--silent","--show-error","--max-time","5","https://124.221.211.156/api/account/health"]).stdout)
            break
        except RuntimeError:time.sleep(.5)
    else:raise RuntimeError("account_public_health_not_ready")
    assert public["omrOwnershipHook"] is True
    run(["/opt/notelite-gateway/deploy/check-health.sh"])
    for name in ("notelite-accounts.service","notelite-gateway.service","notelite-omr.service","nginx.service"):
        run(["systemctl","is-active","--quiet",name])
    print(json.dumps({"status":"passed","accountListener":"127.0.0.1:8771","omrOwnershipHook":True,
                      "certificateBypass":False,"privateKeyLogged":False,"backup":str(BACKUP)}))
except BaseException:
    # Preserve every runtime database, recording and score; restore service code.
    for name,raw in saved.items():
        if raw is not None:
            path=Path(name);path.write_bytes(raw)
    subprocess.run(["systemctl","stop","notelite-accounts.service"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    subprocess.run(["systemctl","daemon-reload"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    subprocess.run(["systemctl","restart","notelite-gateway.service"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    subprocess.run(["nginx","-t"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    subprocess.run(["systemctl","reload","nginx.service"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    print("ROLLBACK: previous gateway/nginx restored; runtime data retained")
    raise
