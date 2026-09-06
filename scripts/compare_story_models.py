#!/usr/bin/env python3
"""Opt-in text-only comparison using the product prompts and synthetic fixtures.

One request per case, at most six cases. No images, database, user photos,
fallback models or automatic retries. Existing application configuration is never
modified; credentials stay in memory and are sent only to the chosen provider.
"""

import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "docs" / "acceptance"
MODELS = {
    "claude-sonnet-5": ("anthropic", 2, 10),
    "claude-opus-5": ("anthropic", 5, 25),
    "gpt-5.6-sol": ("openai", 4, 20),
    "gpt-6-astra": ("openai", 10, 50),
}
TOPICS = [
    ("3-5", "친구와 블록을 번갈아 쓰며 함께 작은 집을 만드는 이야기"),
    ("3-5", "화분에 씨앗을 심고 며칠 기다린 뒤 새싹을 만나는 이야기"),
    ("5-7", "처음 보는 안전한 놀이를 어른과 함께 조금씩 시도하는 이야기"),
    ("5-7", "작은 도서관 지붕에서 비가 새어 어른에게 알리고 안전한 곳에서 친구들과 책을 보호하는 이야기"),
    ("7-9", "친구들과 빗물을 모아 정원을 가꾸며 의견 차이를 해결하는 이야기"),
    ("7-9", "소풍 뒤 숲의 쓰레기를 어른과 함께 안전하게 치우며 작은 약속을 지키는 이야기"),
]
SAFE_FAILURE_CODES = frozenset({
    "HOST_OR_REQUEST_LIMIT", "CASE_REQUEST_LIMIT", "REQUEST_CONTRACT_LIMIT",
    "PROVIDER_KEY_NOT_CONFIGURED", "INVALID_CASES", "INVALID_MODEL",
    "OUTPUT_MUST_BE_IGNORED_ACCEPTANCE_CHILD", "SECRET_IN_OUTPUT",
    "COMPARISON_FAILED",
})


class ComparisonError(Exception):
    """Only fixed local status codes may be exposed."""

    def __init__(self, code):
        super().__init__(code if isinstance(code, str) and code in SAFE_FAILURE_CODES else "COMPARISON_FAILED")


class ValidationDiagnostics:
    """Second allowlist boundary for model-owned paths and fixed failure types."""

    INTEGRITY_RULES = frozenset({
        "invalid_unicode", "requested_language_mismatch",
        "unexpected_latin_in_korean_narrative",
    })

    def __init__(self):
        from typing import get_args
        from pydantic_core import ErrorType
        from src.models.dto import StoryDraft

        self.validation_types = frozenset(get_args(ErrorType)) | {"unknown_validation_error"}
        schema = StoryDraft.model_json_schema()
        self.paths = {"$"}

        def visit(node, path):
            # Only traverse our generated DTO schema, never provider JSON or
            # logger-supplied field names. Array indexes are always anonymous.
            if "$ref" in node:
                visit(schema["$defs"][node["$ref"].rsplit("/", 1)[-1]], path)
            for alternative in node.get("anyOf", []):
                visit(alternative, path)
            for name, child in node.get("properties", {}).items():
                field = f"{path}.{name}" if path else name
                self.paths.add(field)
                visit(child, field)
            if "items" in node:
                self.paths.add(path + "[]")
                visit(node["items"], path + "[]")

        visit(schema, "")
        self.entries = []

    def begin_case(self):
        self.entries = []

    def _collect(self, values, *, source, value_key, allowed):
        if type(values) is not list:
            return
        for value in values[:32]:
            if type(value) is not dict:
                continue
            path, reason = value.get("field_path"), value.get(value_key)
            if (type(path) is not str or path not in self.paths
                    or type(reason) is not str or reason not in allowed):
                continue
            entry = {"source": source, "field_path": path, value_key: reason}
            if entry not in self.entries and len(self.entries) < 24:
                self.entries.append(entry)

    def schema(self, *_args, **kwargs):
        if kwargs.get("schema_model") == "StoryDraft":
            self._collect(kwargs.get("schema_diagnostics"), source="schema",
                          value_key="validation_type", allowed=self.validation_types)

    def integrity(self, *_args, **kwargs):
        self._collect(kwargs.get("integrity_diagnostics"), source="integrity",
                      value_key="rule", allowed=self.INTEGRITY_RULES)


def write_json(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


class RequestBudget:
    def __init__(self, provider, model, limit, transport=None):
        if model not in MODELS or MODELS[model][0] != provider:
            raise ComparisonError("INVALID_MODEL")
        if type(limit) is not int or not 1 <= limit <= 6:
            raise ComparisonError("INVALID_CASES")
        self.provider, self.model, self.limit = provider, model, limit
        self.transport = transport
        self.metrics = []
        self.started_cases = set()
        self.case_requests = None
        self.url = ("https://api.anthropic.com/v1/messages" if provider == "anthropic"
                    else "https://api.openai.com/v1/responses")

    def begin_case(self, case):
        if type(case) is not int or case not in range(1, 7) or case in self.started_cases:
            raise ComparisonError("INVALID_CASES")
        self.started_cases.add(case)
        self.case_requests = 0

    def output_contract(self, payload):
        """Identify the actual wire format without recording caller-owned data."""
        if self.provider == "anthropic":
            protocol = "anthropic_messages"
            config = payload.get("output_config")
            if config is None:
                return {"protocol": protocol, "format": "json_text", "native_schema": False}
            output_format = config.get("format") if type(config) is dict else None
            expected_keys = {"type", "schema"}
        else:
            protocol = "openai_responses"
            text_config = payload.get("text")
            output_format = text_config.get("format") if type(text_config) is dict else None
            if output_format == {"type": "json_object"}:
                return {"protocol": protocol, "format": "json_object", "native_schema": False}
            expected_keys = {"type", "name", "strict", "schema"}
        if (type(output_format) is not dict or set(output_format) != expected_keys
                or output_format.get("type") != "json_schema"
                or (self.provider == "openai" and (
                    output_format.get("name") != "story_draft" or output_format.get("strict") is not True))):
            raise ComparisonError("REQUEST_CONTRACT_LIMIT")
        from src.models.dto import StoryDraft
        from src.services.structured_output import provider_output_schema

        owned_schema = provider_output_schema(StoryDraft.model_json_schema(), provider=self.provider)
        # Canonical JSON comparison also distinguishes bools from numbers. Do
        # not hash or retain a schema with per-request values, unknown fields,
        # child names or injected descriptions, even if it resembles our DTO.
        def canonical(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        actual_schema = output_format.get("schema")
        if type(actual_schema) is not dict or canonical(actual_schema) != canonical(owned_schema):
            raise ComparisonError("REQUEST_CONTRACT_LIMIT")
        return {
            "protocol": protocol, "format": "json_schema", "native_schema": True,
            "schema_model": "StoryDraft",
            "schema_sha256": hashlib.sha256(canonical(actual_schema)).hexdigest(),
            "schema_hash_encoding": "json-sort-keys-compact-utf8",
        }

    def client(self, *, timeout, **_ignored):
        budget = self

        class Client:
            async def __aenter__(self):
                self.http = httpx.AsyncClient(
                    timeout=min(float(timeout), 120), follow_redirects=False, trust_env=False,
                    transport=budget.transport or httpx.AsyncHTTPTransport(retries=0),
                )
                await self.http.__aenter__()
                return self

            async def __aexit__(self, *exc):
                return await self.http.__aexit__(*exc)

            async def post(self, url, *, headers, json):
                if url != budget.url or len(budget.metrics) >= budget.limit:
                    raise ComparisonError("HOST_OR_REQUEST_LIMIT")
                if budget.case_requests != 0:
                    raise ComparisonError("CASE_REQUEST_LIMIT")
                token_field = "max_tokens" if budget.provider == "anthropic" else "max_output_tokens"
                if (json.get("model") != budget.model
                        or type(json.get(token_field)) is not int
                        or not 1 <= json[token_field] <= 12000
                        or json.get("tools") or json.get("stream")
                        or (budget.provider == "openai" and json.get("store") is not False)):
                    raise ComparisonError("REQUEST_CONTRACT_LIMIT")
                metric = {"output_token_cap": json[token_field], "output_contract": budget.output_contract(json)}
                budget.metrics.append(metric)
                budget.case_requests += 1
                started = time.monotonic()
                try:
                    response = await self.http.post(url, headers=headers, json=json)
                    metric["http_status"] = response.status_code
                    try:
                        usage = response.json().get("usage", {})
                        metric["usage"] = {k: usage[k] for k in ("input_tokens", "output_tokens")
                                           if type(usage.get(k)) is int and usage[k] >= 0}
                    except (AttributeError, ValueError):
                        pass
                    return response
                finally:
                    metric["seconds"] = round(time.monotonic() - started, 3)

        return Client()


async def compare(values, model, cases, output_dir, *, transport=None):
    if model not in MODELS:
        raise ComparisonError("INVALID_MODEL")
    provider, input_price, output_price = MODELS[model]
    # A provider-specific comparison key may coexist with the active LLM key.
    key = values.get(f"{provider.upper()}_API_KEY", "")
    if not key and values.get("LLM_PROVIDER") == provider:
        key = values.get("LLM_API_KEY", "")
    key = key.strip()
    if not key or not key.isascii() or any(c.isspace() for c in key):
        raise ComparisonError("PROVIDER_KEY_NOT_CONFIGURED")
    if not cases or len(cases) > 6 or len(set(cases)) != len(cases) or any(type(c) is not int or c not in range(1, 7) for c in cases):
        raise ComparisonError("INVALID_CASES")
    output_dir = output_dir.resolve()
    if output_dir == ACCEPTANCE.resolve() or not output_dir.is_relative_to(ACCEPTANCE.resolve()):
        raise ComparisonError("OUTPUT_MUST_BE_IGNORED_ACCEPTANCE_CHILD")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from src.models.dto import BookSpec
    from src.services import llm, openai_contract, story_integrity

    settings = SimpleNamespace(llm_provider=provider, llm_model=model, llm_api_key=key, llm_timeout=120)
    budget = RequestBudget(provider, model, len(cases), transport)
    report = {
        "scope": "synthetic_text_model_comparison", "model": model, "provider": provider,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "price_usd_per_million": {"input": input_price, "output": output_price},
        "prices_verified_on": "2026-09-06", "price_kind": "standard_short_context_uncached",
        "price_source": ("https://platform.claude.com/docs/en/about-claude/pricing" if provider == "anthropic"
                         else "https://developers.openai.com/api/docs/pricing"),
        "image_requests": 0, "retries": 0, "synthetic_data_only": True,
        "pipeline_verified": False, "moderation_verified": False,
        "quality_scored": False, "launch_ready": False, "cases": [],
        "prompt_files_sha256": {name: hashlib.sha256((llm.PROMPTS_DIR / name).read_bytes()).hexdigest()
                                for name in ("generate_story.system.jinja2", "generate_story.user.jinja2")},
    }
    silent = SimpleNamespace(**{name: lambda *a, **k: None for name in ("info", "warning", "error", "debug")})
    diagnostics = ValidationDiagnostics()
    schema_logger = SimpleNamespace(**{**vars(silent), "error": diagnostics.schema})
    integrity_logger = SimpleNamespace(**{**vars(silent), "warning": diagnostics.integrity})
    guarded_http = SimpleNamespace(
        AsyncClient=budget.client, TimeoutException=httpx.TimeoutException,
        HTTPError=httpx.HTTPError,
    )
    old_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(llm, "settings", settings))
            stack.enter_context(patch.object(llm, "httpx", guarded_http))
            stack.enter_context(patch.object(llm, "logger", schema_logger))
            # The shared Responses adapter owns its own HTTP import. Applying
            # the same boundary here prevents it bypassing the request budget,
            # host allowlist, inert test transport and redirect/proxy controls.
            stack.enter_context(patch.object(openai_contract, "httpx", guarded_http))
            stack.enter_context(patch.object(openai_contract, "logger", silent))
            stack.enter_context(patch.object(story_integrity, "logger", integrity_logger))
            for case in cases:
                budget.begin_case(case)
                diagnostics.begin_case()
                age, topic = TOPICS[case - 1]
                spec = BookSpec(topic=topic, target_age=age, style="watercolor", page_count=4,
                                protagonist_name="하루", character={
                                    "name": "하루", "appearance": "짧은 검은 단발머리, 노란 멜빵바지, 초록 장화",
                                    "personality": ["다정함", "호기심"],
                                })
                result = {"case": case, "age": age, "status": "failed", "spec": spec.model_dump(mode="json")}
                before = len(budget.metrics)
                try:
                    story = await asyncio.wait_for(llm.call_story_generation(spec), timeout=125)
                    serialized = story.model_dump_json()
                    secrets = [v for k, v in values.items() if k.endswith("API_KEY") and isinstance(v, str) and len(v) >= 12]
                    if key in serialized or any(secret in serialized for secret in secrets):
                        raise ComparisonError("SECRET_IN_OUTPUT")
                    artifact = f"case-{case}.json"
                    write_json(output_dir / artifact, story.model_dump(mode="json"))
                    result.update(status="structurally_valid", artifact=artifact)
                except Exception as error:
                    code = getattr(error, "code", None)
                    allowed = {"LLM_JSON_INVALID", "LLM_TIMEOUT", "SAFETY_OUTPUT"}
                    code_value = getattr(code, "value", code)
                    result["failure"] = (code_value if code_value in allowed else
                                         str(error) if isinstance(error, ComparisonError) else
                                         "TIMEOUT" if isinstance(error, (TimeoutError, httpx.TimeoutException)) else "PROVIDER_FAILED")
                result["requests"] = budget.metrics[before:]
                result["validation_diagnostics"] = list(diagnostics.entries)
                report["cases"].append(result)
                write_json(output_dir / f"case-{case}-result.json", result)
                print(f"Case {case}: {result['status']}", flush=True)
                if any(m.get("http_status") in {401, 402, 403, 429} for m in result["requests"]):
                    report["stopped_reason"] = "PROVIDER_ACCESS_OR_QUOTA"
                    break
    finally:
        logging.disable(old_logging)
        report["request_count"] = len(budget.metrics)
        contracts = []
        for metric in budget.metrics:
            contract = metric["output_contract"]
            if contract not in contracts:
                contracts.append(contract)
        report["output_contracts"] = contracts
        native_values = {contract["native_schema"] for contract in contracts}
        report["native_schema"] = next(iter(native_values)) if len(native_values) == 1 else None
        report["native_schema_request_count"] = sum(m["output_contract"]["native_schema"] for m in budget.metrics)
        report["estimated_usd"] = round(sum(
            m.get("usage", {}).get("input_tokens", 0) * input_price
            + m.get("usage", {}).get("output_tokens", 0) * output_price
            for m in budget.metrics) / 1_000_000, 6)
        report["unstarted_cases"] = cases[len(report["cases"]):]
        write_json(output_dir / "comparison.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, action="append", required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--cases", type=int, nargs="+", default=list(range(1, 7)))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; this consumes existing provider credit")
    values = {}
    try:
        for path in args.env_file:
            values.update({k: v or "" for k, v in dotenv_values(path, interpolate=False).items()})
        report = asyncio.run(compare(values, args.model, args.cases, args.output_dir))
        return 0 if all(c["status"] == "structurally_valid" for c in report["cases"]) and not report["unstarted_cases"] else 1
    except ComparisonError as error:
        print(str(error))
        return 1
    except Exception:
        print("COMPARISON_FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
