"""Read-only operational snapshot; nonzero exit means investigate, never auto-retry generation."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from final_external_preflight import public_https_endpoint


def assess(payload):
    alerts = []
    if not isinstance(payload, dict):
        return {"status": "ALERT", "alerts": ["invalid_health_response"]}
    if payload.get("status") != "healthy":
        alerts.append("readiness_unhealthy")
    jobs = payload.get("jobs")
    jobs = jobs if isinstance(jobs, dict) else {}
    counts = {}
    for name in ("queued", "running", "stuck", "completed_last_hour", "failed_last_hour"):
        value = jobs.get(name)
        if type(value) is not int or value < 0:
            alerts.append("job_metrics_unavailable")
            break
        counts[name] = value
    if counts.get("stuck", 0):
        alerts.append("stuck_jobs")
    if counts.get("failed_last_hour", 0):
        alerts.append("generation_failures_last_hour")
    budget = payload.get("generation_budget")
    budget = budget if isinstance(budget, dict) else {}
    used, limit = budget.get("used"), budget.get("limit")
    if type(used) is not int or type(limit) is not int or used < 0 or limit <= 0:
        alerts.append("generation_budget_unavailable")
        used = limit = None
    elif used >= limit * 0.8:
        alerts.append("generation_budget_near_limit")
    # Never forward arbitrary health fields: they may contain internal identifiers.
    return {"status": "ALERT" if alerts else "OK", "alerts": alerts,
            "jobs": counts, "generation_requests": {"used": used, "limit": limit}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Assess a saved detailed-health JSON without network")
    args = parser.parse_args()
    try:
        if args.input:
            payload = json.loads(args.input.read_text())
        else:
            url = os.environ.get("PROD_API_URL", "").rstrip("/")
            key = os.environ.get("ADMIN_API_KEY", "")
            parsed = urlsplit(url)
            if (not key or not public_https_endpoint(url) or parsed.path
                    or parsed.query or parsed.fragment):
                raise ValueError("Public HTTPS origin and admin credential required")
            # No redirects/proxies: do not forward the admin header to another host.
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                response = client.get(url + "/health/detailed", headers={"X-Admin-Key": key})
                response.raise_for_status()
                payload = response.json()
        result = assess(payload)
    except (OSError, ValueError, httpx.HTTPError):
        result = {"status": "ALERT", "alerts": ["operational_probe_unavailable"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["status"] != "OK")


if __name__ == "__main__":
    raise SystemExit(main())
