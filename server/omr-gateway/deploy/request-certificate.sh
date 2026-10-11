#!/usr/bin/env bash
set -euo pipefail
ip=124.221.211.156
agree=false
email=''
no_email=false
staging=false
while (($#)); do
    case "$1" in
        --agree-tos) agree=true; shift ;;
        --email) [[ $# -ge 2 ]] || { echo 'Missing email' >&2; exit 2; }; email=$2; shift 2 ;;
        --without-email) no_email=true; shift ;;
        --staging) staging=true; shift ;;
        *) echo 'Usage: request-certificate.sh --agree-tos (--email ADDRESS | --without-email) [--staging]' >&2; exit 2 ;;
    esac
done
[[ "$agree" == true ]] || { echo 'ERROR: issuing a certificate requires explicit --agree-tos authorization.' >&2; exit 2; }
if [[ -n "$email" && "$no_email" == true ]] || [[ -z "$email" && "$no_email" == false ]]; then
    echo 'ERROR: choose exactly one of --email ADDRESS or --without-email.' >&2; exit 2
fi
certbot=/opt/notelite-certbot/bin/certbot
[[ -x "$certbot" ]] || { echo 'ERROR: run install.sh bootstrap first.' >&2; exit 1; }
"$certbot" --version
args=(certonly --non-interactive --agree-tos --preferred-profile shortlived --webroot
      --webroot-path /var/www/notelite-acme --ip-address "$ip" --cert-name "$ip"
      --deploy-hook /opt/notelite-gateway/deploy/reload-nginx.sh)
if [[ -n "$email" ]]; then args+=(--email "$email"); else args+=(--register-unsafely-without-email); fi
if [[ "$staging" == true ]]; then
    # Keep staging separate: do not install an untrusted certificate into the live path.
    args+=(--staging --config-dir /etc/notelite-acme-staging --work-dir /var/lib/notelite-acme-staging --logs-dir /var/log/notelite-acme-staging)
fi
exec "$certbot" "${args[@]}"
