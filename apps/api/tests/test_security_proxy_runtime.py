"""Opt-in real Caddy/nginx checks using isolated Docker containers and fake IPs.

ASB_TEST_PROXY_RUNTIME=1 pytest tests/test_security_proxy_runtime.py -q
ASB_SECURITY_BASELINE=1 uses the original scanned configs at da07a30.
No cloud credentials, real users, provider requests or published non-loopback ports.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[3]
BASELINE = os.environ.get("ASB_SECURITY_BASELINE") == "1"
pytestmark = pytest.mark.skipif(os.environ.get("ASB_TEST_PROXY_RUNTIME") != "1",
                                reason="opt-in Docker proxy boundary test")


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


@pytest.fixture(scope="module")
def proxies(tmp_path_factory):
    root = tmp_path_factory.mktemp("proxy-runtime")
    network = "asb-security-" + uuid.uuid4().hex[:10]
    containers = []
    command("docker", "network", "create", network)
    gateway = json.loads(command("docker", "network", "inspect", network))[0]["IPAM"]["Config"][0]["Gateway"]

    def start(name, image, *arguments, mounts=(), env=()):
        name = network + "-" + name
        cmd = ["docker", "run", "-d", "--name", name, "--network", network,
               "--network-alias", name.rsplit("-", 1)[-1]]
        for mount in mounts:
            cmd += ["-v", mount]
        for value in env:
            cmd += ["-e", value]
        # Each container exposes only an ephemeral loopback port to the host.
        if name.endswith("edge"):
            cmd += ["-p", "127.0.0.1::8080"]
        if name.endswith("nginx"):
            cmd += ["-p", "127.0.0.1::80", "-p", "127.0.0.1::443"]
        command(*cmd, image, *arguments)
        containers.append(name)
        return name

    def port(name, number):
        return int(command("docker", "port", name, str(number)).rsplit(":", 1)[1])

    def source(path):
        if BASELINE:
            return command("git", "-C", str(ROOT), "show", "da07a30:" + path)
        return (ROOT / path).read_text()

    try:
        command("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-keyout", str(root / "privkey.pem"), "-out", str(root / "fullchain.pem"),
                "-subj", "/CN=35.209.174.246", "-addext", "subjectAltName=IP:35.209.174.246")
        app = '''from http.server import BaseHTTPRequestHandler, HTTPServer
class App(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path.endswith('/fixture-failure'):
   self.connection.close(); return
  self.send_response(200); self.end_headers()
  self.wfile.write(self.headers.get('X-Forwarded-For', 'absent').encode())
 def log_message(self, *args): pass
HTTPServer(('0.0.0.0', 8000), App).serve_forever()
'''
        (root / "echo.py").write_text(app)
        api = start("api", "asb-hybrid-api:review-20261111-hybrid-r3", "python", "/echo.py",
                    mounts=[f"{root}/echo.py:/echo.py:ro"])
        config = source("infra/nginx/nginx.conf")
        (root / "nginx.conf").write_text(config)
        # Only the test edge's exact IP is trusted. Populate after it starts.
        (root / "trusted-edge.conf").write_text("")
        nginx = start("nginx", "nginx:1.28-alpine", mounts=[
            f"{root}/nginx.conf:/etc/nginx/nginx.conf:ro",
            f"{root}/trusted-edge.conf:/etc/nginx/trusted-edge.conf:ro",
            f"{root}/fullchain.pem:/etc/nginx/ssl/fullchain.pem:ro",
            f"{root}/privkey.pem:/etc/nginx/ssl/privkey.pem:ro",
        ])
        caddy = source("infra/gcp-pilot/cloud-run-https-edge/Caddyfile")
        caddy = caddy.replace("https://10.128.0.2:443", "https://nginx:443")
        # Trust only the locally generated certificate; all TLS checks stay on.
        caddy = caddy.replace("transport http {", "transport http {\n        tls_trust_pool file /fixture.crt")
        (root / "Caddyfile").write_text(caddy)
        edge = start("edge", "caddy:2.11.2-alpine", mounts=[
            f"{root}/Caddyfile:/etc/caddy/Caddyfile:ro",
            f"{root}/fullchain.pem:/fixture.crt:ro",
        ], env=[f"CLOUD_RUN_TRUSTED_PROXY_CIDRS={gateway}/32"])
        # The host connection arrives through the exact Docker network gateway,
        # emulating Cloud Run's serving peer. Other XFF hops stay untrusted.
        edge_ip = json.loads(command("docker", "inspect", edge))[0]["NetworkSettings"]["Networks"][network]["IPAddress"]
        (root / "trusted-edge.conf").write_text(f"set_real_ip_from {edge_ip};\n")
        command("docker", "exec", nginx, "nginx", "-t")
        command("docker", "exec", nginx, "nginx", "-s", "reload")
        edge_url = f"http://127.0.0.1:{port(edge, 8080)}"
        with httpx.Client(timeout=10) as client:
            for _ in range(60):
                try:
                    if client.get(edge_url + "/v1/fixture").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("proxy fixture failed to become ready: " + command("docker", "logs", edge))
        yield {"root": root, "nginx": nginx, "api": api, "edge_url": edge_url,
               "http": f"http://127.0.0.1:{port(nginx, 80)}",
               "https": f"https://127.0.0.1:{port(nginx, 443)}"}
    finally:
        for name in reversed(containers):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


@pytest.mark.asyncio
async def test_distinct_visitors_and_spoofed_headers_reach_distinct_recovery_buckets(proxies, monkeypatch):
    from src.routers.account import check_recovery_rate_limit
    from src.core.rate_limit import rate_limiter
    from src.core.exceptions import RateLimitError
    from tests.fake_redis import FakeRedis
    redis = FakeRedis()
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=redis))
    values = []
    with httpx.Client(timeout=10) as client:
        for chain in ("192.0.2.9, 198.51.100.1", "192.0.2.9, 198.51.100.2",
                      "203.0.113.8, 198.51.100.1", "2001:db8::9, 2001:db8::1"):
            result = client.get(proxies["edge_url"] + "/v1/fixture", headers={"X-Forwarded-For": chain})
            assert result.status_code == 200
            # Uvicorn trusts nginx alone and takes the rightmost remaining hop.
            peer = result.text.split(",")[-1].strip()
            values.append(peer)
            await check_recovery_rate_limit(Request({"type": "http", "client": (peer, 1)}))
    if BASELINE:
        assert len(set(values)) == 1
        assert len(redis.sorted_sets) == 1
    else:
        assert values == ["198.51.100.1", "198.51.100.2", "198.51.100.1", "2001:db8::1"]
        assert len(redis.sorted_sets) == 3
        assert len(redis.sorted_sets["account_recovery:" + hashlib.sha256(values[0].encode()).hexdigest()]) == 2
    redis.sorted_sets.clear()
    attacker = Request({"type": "http", "client": (values[0], 1)})
    victim = Request({"type": "http", "client": (values[1], 1)})
    for _ in range(10):
        await check_recovery_rate_limit(attacker)
    with pytest.raises(RateLimitError):
        await check_recovery_rate_limit(attacker)
    if BASELINE:
        with pytest.raises(RateLimitError):
            await check_recovery_rate_limit(victim)
    else:
        await check_recovery_rate_limit(victim)
    # A direct, untrusted nginx connection must not adopt supplied XFF.
    with httpx.Client(verify=False, timeout=10) as client:
        direct = client.get(proxies["https"] + "/v1/fixture", headers={"X-Forwarded-For": "203.0.113.99"})
    assert direct.status_code == 200
    assert direct.text.split(",")[-1].strip() != "203.0.113.99"


def test_share_redirect_upstream_failure_and_internal_error_page_never_log_token(proxies):
    token = "synthetic-capability-" + uuid.uuid4().hex
    with httpx.Client(verify=False, timeout=10) as client:
        for path in (f"/share/{token}", f"/%73hare/{token}"):
            redirect = client.get(proxies["http"] + path)
            assert redirect.status_code == 301
            if not BASELINE:
                assert redirect.headers["cache-control"] == "private, no-store"
        normal = client.get(proxies["https"] + "/share/" + token)
        assert normal.status_code == 200
        if not BASELINE:
            assert normal.headers["referrer-policy"] == "no-referrer"
        failure = client.get(proxies["https"] + "/share/" + token + "/fixture-failure")
        assert failure.status_code in {500, 502, 503, 504}
        command("docker", "exec", proxies["nginx"], "rm", "-f", "/usr/share/nginx/html/50x.html")
        nested = client.get(proxies["https"] + "/share/" + token + "/fixture-failure")
        assert nested.status_code in {404, 500, 502, 503, 504}
        # Preserve diagnostics for unrelated requests.
        client.get(proxies["http"] + "/ordinary-diagnostic")
    logs = command("docker", "logs", proxies["nginx"])
    assert "/ordinary-diagnostic" in logs
    assert (token in logs) is BASELINE
