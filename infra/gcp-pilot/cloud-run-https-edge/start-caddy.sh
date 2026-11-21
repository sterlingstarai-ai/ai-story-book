#!/bin/sh
set -eu
: "${CLOUD_RUN_TRUSTED_PROXY_CIDRS:?Set the verified Cloud Run serving peer CIDRs}"
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
