#!/usr/bin/env bash
set -euo pipefail
ip=124.221.211.156
local_only=false
if [[ ${1:-} == --local-only ]]; then local_only=true; shift; fi
[[ $# -eq 0 ]] || { echo 'Usage: check-health.sh [--local-only]' >&2; exit 2; }
cert=/etc/letsencrypt/live/$ip/fullchain.pem
[[ -s "$cert" ]] || { echo 'ERROR: live certificate missing.' >&2; exit 1; }
/usr/bin/openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt -untrusted "$cert" -verify_ip "$ip" "$cert"
/usr/bin/openssl x509 -in "$cert" -noout -checkend 129600
echo 'PASS: IP SAN and at least 36 hours of certificate validity'
/usr/bin/systemctl is-active --quiet notelite-omr.service
/usr/bin/systemctl is-active --quiet notelite-gateway.service
/usr/bin/systemctl is-active --quiet nginx.service
/usr/bin/systemctl is-active --quiet notelite-cert-renew.timer
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=10) as response:
    result = json.load(response)
if not isinstance(result, dict) or result.get('status') != 'ok' or result.get('service') != 'notelite-omr':
    raise SystemExit('ERROR: OMR health is not healthy')
print('PASS: loopback OMR health')
PY
tmp=$(mktemp)
trap 'rm -f -- "$tmp"' EXIT
curl --fail --silent --show-error --connect-timeout 10 --max-time 30 --resolve "$ip:443:127.0.0.1" "https://$ip/api/health" --output "$tmp"
python3 - "$tmp" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    result = json.load(handle)
if not isinstance(result, dict) or result.get('status') != 'ok' or result.get('gateway') != 'device-scoped':
    raise SystemExit('ERROR: gateway health is not healthy')
print('PASS: trusted local HTTPS and gateway health')
PY
if [[ "$local_only" == false ]]; then
    curl --fail --silent --show-error --connect-timeout 10 --max-time 30 "https://$ip/api/health" --output "$tmp"
    python3 - "$tmp" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    result = json.load(handle)
if not isinstance(result, dict) or result.get('status') != 'ok' or result.get('gateway') != 'device-scoped':
    raise SystemExit('ERROR: public gateway health is not healthy')
print('PASS: public-route HTTPS gateway health (repeat from an external device)')
PY
fi
