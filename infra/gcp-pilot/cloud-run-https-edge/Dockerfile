FROM caddy@sha256:834468128c7696cec0ceea6172f7d692daf645ae51983ca76e39da54a97c570d
COPY Caddyfile /etc/caddy/Caddyfile
COPY upstream-client-auth.caddy /etc/caddy/upstream-client-auth.caddy
COPY start-caddy.sh /usr/local/bin/start-caddy
CMD ["/bin/sh", "/usr/local/bin/start-caddy"]
