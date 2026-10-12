#!/usr/bin/env bash
set -euo pipefail
umask 0077
[[ ${EUID} -eq 0 ]] || { echo 'ERROR: run as root.' >&2; exit 1; }
output=''
owner=''
ttl=600
while (($#)); do
    case "$1" in
        --output) [[ $# -ge 2 ]] || exit 2; output=$2; shift 2 ;;
        --owner) [[ $# -ge 2 ]] || exit 2; owner=$2; shift 2 ;;
        --ttl) [[ $# -ge 2 ]] || exit 2; ttl=$2; shift 2 ;;
        *) echo 'Usage: issue-pairing.sh --output /var/lib/notelite-gateway/NAME.pairing.json [--owner UUID] [--ttl SECONDS]' >&2; exit 2 ;;
    esac
done
[[ -n "$output" && "$ttl" =~ ^[0-9]+$ ]] || { echo 'ERROR: explicit private output path and numeric ttl are required.' >&2; exit 2; }
root=/var/lib/notelite-gateway
resolved=$(realpath -m -- "$output")
case "$resolved" in
    "$root"/*.pairing.json) ;;
    *) echo 'ERROR: pairing file must remain inside /var/lib/notelite-gateway and end with .pairing.json.' >&2; exit 2 ;;
esac
[[ ! -e "$resolved" && ! -L "$resolved" ]] || { echo 'ERROR: refusing to overwrite a pairing file.' >&2; exit 1; }
args=(/usr/bin/python3 /opt/notelite-gateway/gateway.py
      --storage "$root" --public-origin https://124.221.211.156
      pair --output "$resolved" --ttl "$ttl")
[[ -z "$owner" ]] || args+=(--owner "$owner")
# Creates as the service user, mode 0600. The code is never printed to logs.
exec /usr/sbin/runuser -u audiveris -- "${args[@]}"
