#!/usr/bin/env python3
"""Check AI configuration, or explicitly request read-only provider model metadata."""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re

import httpx
from dotenv import dotenv_values


PROVIDERS = {
    "anthropic": ("https://api.anthropic.com/v1/models", "claude-"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "gemini-"),
}
MAX_METADATA_BYTES = 2 * 1024 * 1024


def safe_model(value, provider, secret):
    """Allow model identifiers only; never echo credentials or provider free text."""
    if not isinstance(value, str) or not value.startswith(PROVIDERS[provider][1]):
        return None
    if secret and secret in value:
        return None
    return value if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{1,127}", value) else None


def configured_key(value):
    lowered = value.lower()
    return bool(value) and value.isascii() and not any(c.isspace() for c in value) and not any(
        marker in lowered for marker in ("your-", "your_", "placeholder", "change_me", "test-key", "mock")
    )


def http_failure(status):
    if status in {401, 403, 404, 429}:
        return {401: "AUTHENTICATION_FAILED", 403: "PERMISSION_DENIED",
                404: "MODEL_UNAVAILABLE", 429: "RATE_LIMITED"}[status]
    if 300 <= status < 400:
        return "REDIRECT_REFUSED"
    return "PROVIDER_UNAVAILABLE" if status >= 500 else "REQUEST_REJECTED"


def check_component(values, role, *, live=False, list_models=False, client=None):
    prefix = role.upper()
    provider = values.get(f"{prefix}_PROVIDER", "").strip().lower()
    secret = values.get(f"{prefix}_API_KEY", "").strip()
    model = values.get(f"{prefix}_MODEL", "").strip()
    result = {"component": role, "provider": provider if provider in PROVIDERS else "unsupported",
              "status": "NOT_CONFIGURED", "metadata_verified": False}
    if provider not in PROVIDERS or (role == "image" and provider != "gemini"):
        result["status"] = "UNSUPPORTED_PROVIDER"
        return result
    if not configured_key(secret):
        return result
    selected_model = safe_model(model, provider, secret)
    if selected_model:
        result["configured_model"] = selected_model
    elif not list_models:
        result["status"] = "INVALID_MODEL_CONFIGURATION"
        return result
    result["status"] = "CONFIGURED_NOT_VERIFIED"
    if not live:
        return result
    if client is None:
        raise ValueError("A client is required for explicit live metadata checks")

    url = PROVIDERS[provider][0]
    headers = {"x-api-key": secret, "anthropic-version": "2023-06-01"} if provider == "anthropic" else {
        "x-goog-api-key": secret,
    }
    params = {"limit": 1000} if provider == "anthropic" else {"pageSize": 1000}
    if not list_models:
        url += f"/{selected_model}"
        params = None
    try:
        # Fixed HTTPS hosts, headers only, no redirects, no retries or generation requests.
        with client.stream("GET", url, headers=headers, params=params) as response:
            result["http_status"] = response.status_code
            if response.status_code != 200:
                result["status"] = http_failure(response.status_code)
                return result
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_METADATA_BYTES:
                    result["status"] = "INVALID_METADATA"
                    return result
        payload = json.loads(body)
    except httpx.TimeoutException:
        result["status"] = "NETWORK_TIMEOUT"
        return result
    except httpx.HTTPError:
        result["status"] = "NETWORK_ERROR"
        return result
    except (ValueError, UnicodeError):
        result["status"] = "INVALID_METADATA"
        return result

    if not isinstance(payload, dict):
        result["status"] = "INVALID_METADATA"
        return result
    entries = payload.get("data" if provider == "anthropic" else "models") if list_models else [payload]
    if not isinstance(entries, list):
        result["status"] = "INVALID_METADATA"
        return result
    models = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id" if provider == "anthropic" else "name", "")
        if provider == "gemini" and isinstance(raw_id, str):
            raw_id = raw_id.removeprefix("models/")
        resolved = safe_model(raw_id, provider, secret)
        if not resolved:
            continue
        if provider == "gemini":
            methods = entry.get("supportedGenerationMethods", [])
            if not isinstance(methods, list) or "generateContent" not in methods:
                continue
        models.append(resolved)
    if list_models:
        result["available_models"] = sorted(set(models))
        result["list_complete"] = not bool(payload.get("has_more") if provider == "anthropic"
                                           else payload.get("nextPageToken"))
        result["status"] = "METADATA_VERIFIED"
    elif models and (provider == "anthropic" or models[0] == selected_model):
        result["resolved_model"] = models[0]
        result["status"] = "METADATA_VERIFIED"
    else:
        result["status"] = "MODEL_METADATA_UNSUPPORTED"
    result["metadata_verified"] = result["status"] == "METADATA_VERIFIED"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, action="append", default=[],
                        help="Explicit dotenv file, repeatable; file values override ambient variables")
    parser.add_argument("--component", choices=("llm", "image", "both"), default="both")
    parser.add_argument("--live", action="store_true", help="Allow GET requests for provider metadata only")
    parser.add_argument("--list-models", action="store_true",
                        help="List one page of model IDs instead of verifying the configured model")
    args = parser.parse_args(argv)
    # Never let third-party debug logging expose credential headers or provider bodies.
    for logger in ("httpx", "httpcore", "dotenv.main"):
        logging.getLogger(logger).disabled = True
    values = dict(os.environ)
    try:
        for path in args.env_file:
            if not path.is_file():
                raise OSError()
            values.update({key: value or "" for key, value in dotenv_values(path, interpolate=False).items()})
    except (OSError, UnicodeError):
        print(json.dumps({"status": "ENV_FILE_UNREADABLE", "generation_verified": False}))
        return 1
    roles = ("llm", "image") if args.component == "both" else (args.component,)
    # No ambient proxies or alternate hosts: secrets go only to their named provider.
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
        components = [check_component(values, role, live=args.live, list_models=args.list_models,
                                      client=client) for role in roles]
    accepted = {"METADATA_VERIFIED"} if args.live else {"CONFIGURED_NOT_VERIFIED"}
    ok = all(component["status"] in accepted for component in components)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": ("METADATA_VERIFIED" if args.live else "CONFIGURED_NOT_VERIFIED") if ok else "BLOCKED",
        "live_metadata_requested": args.live,
        "generation_requests": 0,
        "generation_verified": False,
        "billing_and_quota_verified": False,
        "launch_ready": False,
        "components": components,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
