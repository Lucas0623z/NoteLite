#!/usr/bin/env bash
set -euo pipefail
umask 0027
[[ ${EUID} -eq 0 ]] || { echo 'ERROR: run as root.' >&2; exit 1; }
phase=${1:-}
[[ "$phase" == bootstrap || "$phase" == https ]] || { echo 'Usage: install.sh bootstrap --gateway PATH --static-dist DIST [--certbot-version 5.4.0] | install.sh https' >&2; exit 2; }
shift
gateway=''
dist=''
version=5.4.0
while (($#)); do
    case "$1" in
        --gateway) [[ $# -ge 2 ]] || exit 2; gateway=$2; shift 2 ;;
        --static-dist) [[ $# -ge 2 ]] || exit 2; dist=$2; shift 2 ;;
        --certbot-version) [[ $# -ge 2 ]] || exit 2; version=$2; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
target=/opt/notelite-gateway
site=/etc/nginx/sites-available/notelite-omr-gateway.conf
marker='NoteLite OMR gateway deployment v1'
if [[ -e "$target" && ! -f "$target/.notelite-managed" ]]; then
    echo 'ERROR: refusing to overwrite an unmanaged /opt/notelite-gateway.' >&2; exit 1
fi
if [[ -e "$site" ]] && ! grep -Fqx -- "# Managed by $marker" "$site"; then
    echo 'ERROR: refusing to overwrite an unmanaged nginx site.' >&2; exit 1
fi
if [[ "$phase" == bootstrap ]]; then
    [[ -f "$gateway" && -f "$dist/index.html" ]] || { echo 'ERROR: provide the gateway source and a built static dist/index.html.' >&2; exit 2; }
    [[ ! -L "$gateway" && ! -L "$dist" ]] || { echo 'ERROR: source paths cannot be symlinks.' >&2; exit 2; }
    [[ -z $(find "$dist" -type l -print -quit) ]] || { echo 'ERROR: static dist must not contain symlinks.' >&2; exit 2; }
    manifest=$(dirname -- "$gateway")/manifest.json
    if [[ -f "$manifest" ]]; then
        python3 - "$manifest" <<'PY'
import hashlib, json, pathlib, sys
manifest = pathlib.Path(sys.argv[1])
root = manifest.parent
for name, expected in json.loads(manifest.read_text()).items():
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('ERROR: gateway source checksum mismatch: ' + name)
print('PASS: gateway source manifest')
PY
    fi
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'ERROR: pin an exact Certbot version.' >&2; exit 2; }
    python3 - "$version" <<'PY'
import sys
if tuple(map(int, sys.argv[1].split('.'))) < (5, 4, 0):
    raise SystemExit('ERROR: webroot IP certificates need Certbot 5.4.0 or newer')
PY
    id audiveris >/dev/null
    test -r /var/lib/audiveris/access-token
    systemctl is-active --quiet notelite-omr.service
    # This installs software only. No cloud security-group or UFW changes are made.
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y nginx python3-venv ca-certificates curl openssl
    install -d -m 0755 "$target" "$target/deploy" /var/www/notelite-acme
    printf '%s\n' "$marker" > "$target/.notelite-managed"
    install -m 0644 "$gateway" "$target/gateway.py"
    for name in render_nginx.py install.sh request-certificate.sh reload-nginx.sh renew-certificate.sh check-health.sh issue-pairing.sh; do
        install -m 0755 "$source_dir/$name" "$target/deploy/$name"
    done
    for name in notelite-gateway.service notelite-cert-renew.service notelite-cert-renew.timer; do
        path=/etc/systemd/system/$name
        if [[ -e "$path" ]] && ! cmp -s "$source_dir/$name" "$path"; then
            echo "ERROR: refusing to overwrite an existing different unit: $path" >&2; exit 1
        fi
        install -m 0644 "$source_dir/$name" "$path"
    done
    install -d -o audiveris -g audiveris -m 0700 /var/lib/notelite-gateway
    if [[ -e /opt/notelite-certbot && ! -f /opt/notelite-certbot/.notelite-managed ]]; then
        echo 'ERROR: refusing to alter an unmanaged Certbot environment.' >&2; exit 1
    fi
    python3 -m venv /opt/notelite-certbot
    printf '%s\n' "$marker" > /opt/notelite-certbot/.notelite-managed
    /opt/notelite-certbot/bin/python -m pip install "certbot==$version"
    /opt/notelite-certbot/bin/certbot --version
    # Publish a new immutable static directory and switch only our own symlink.
    install -d -m 0755 /var/www/notelite-releases
    release=$(mktemp -d /var/www/notelite-releases/ui-XXXXXXXX)
    cp -a -- "$dist/." "$release/"
    chmod -R a+rX -- "$release"
    if [[ -e /var/www/notelite-ui || -L /var/www/notelite-ui ]]; then
        [[ -L /var/www/notelite-ui ]] || { echo 'ERROR: existing static root is not a managed symlink.' >&2; exit 1; }
        case $(readlink -f /var/www/notelite-ui) in
            /var/www/notelite-releases/ui-*) ;;
            *) echo 'ERROR: refusing to replace an unmanaged static symlink.' >&2; exit 1 ;;
        esac
    fi
    ln -s -- "$release" /var/www/notelite-ui.next
    mv -Tf -- /var/www/notelite-ui.next /var/www/notelite-ui
    systemctl daemon-reload
    systemctl enable --now notelite-gateway.service
else
    [[ -f "$target/.notelite-managed" ]] || { echo 'ERROR: bootstrap is required first.' >&2; exit 1; }
    [[ -s /etc/letsencrypt/live/124.221.211.156/fullchain.pem && -s /etc/letsencrypt/live/124.221.211.156/privkey.pem ]] || { echo 'ERROR: trusted production certificate is required first.' >&2; exit 1; }
    openssl x509 -in /etc/letsencrypt/live/124.221.211.156/fullchain.pem -noout -checkend 129600
fi
candidate=$(mktemp)
backup=$(mktemp)
had_site=false
[[ ! -f "$site" ]] || { cp -- "$site" "$backup"; had_site=true; }
python3 "$target/deploy/render_nginx.py" --stage "$phase" --output "$candidate"
install -m 0644 "$candidate" "$site"
enabled=/etc/nginx/sites-enabled/notelite-omr-gateway.conf
if [[ -e "$enabled" || -L "$enabled" ]]; then
    [[ -L "$enabled" && $(readlink -f "$enabled") == "$site" ]] || { echo 'ERROR: unmanaged enabled nginx entry.' >&2; exit 1; }
else
    ln -s -- "$site" "$enabled"
fi
if ! nginx -t; then
    if [[ "$had_site" == true ]]; then cp -- "$backup" "$site"; else rm -f -- "$enabled" "$site"; fi
    rm -f -- "$candidate" "$backup"
    echo 'ERROR: nginx rejected the candidate; previous site restored.' >&2; exit 1
fi
rm -f -- "$candidate" "$backup"
systemctl enable --now nginx.service
systemctl reload nginx.service
if [[ "$phase" == https ]]; then
    systemctl enable --now notelite-cert-renew.timer
    "$target/deploy/check-health.sh"
else
    echo 'Bootstrap HTTP ACME route is ready. Authorize and request the IP certificate, then run install.sh https.'
fi
