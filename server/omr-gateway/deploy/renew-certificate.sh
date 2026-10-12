#!/usr/bin/env bash
set -euo pipefail
certbot=/opt/notelite-certbot/bin/certbot
[[ -x "$certbot" ]] || { echo 'ERROR: managed Certbot is missing' >&2; exit 1; }
# Normal ARI/Certbot renewal scheduling; do not force needless hourly issuance.
"$certbot" renew --non-interactive --cert-name 124.221.211.156
/opt/notelite-gateway/deploy/check-health.sh --local-only
