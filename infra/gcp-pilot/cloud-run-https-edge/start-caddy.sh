#!/bin/sh
set -eu
: "${CLOUD_RUN_TRUSTED_PROXY_CIDRS:?Set the verified Cloud Run serving peer CIDRs}"
case "${ASB_EDGE_CLIENT_AUTH:-none}" in
  mtls)
    test -s /var/run/asb-edge/client.pem || { echo "Upstream client certificate is unavailable" >&2; exit 1; }
    export ASB_EDGE_TLS_INCLUDE=/etc/caddy/upstream-client-auth.caddy
    ;;
  none) export ASB_EDGE_TLS_INCLUDE='/etc/caddy/unused-client-auth-*.caddy' ;;
  *) echo "Unsupported upstream client authentication mode" >&2; exit 1 ;;
esac
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
