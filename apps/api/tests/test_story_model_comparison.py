"""The opt-in comparison must never bypass its cost, host or secret boundary."""

import importlib.util
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.services import llm, openai_contract


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("story_model_comparison", root / "scripts/compare_story_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ACCEPTANCE", tmp_path / "acceptance")
    return module


def story_payload(extra_text=""):
    return {
        "title": "하루의 작은 정원", "language": "ko", "target_age": "3-5", "moral": "함께 돌봐요.",
        "characters": [{"id": "hero", "name": "하루", "role": "main", "brief": "다정한 아이"}],
        "cover": {"cover_text": "하루의 작은 정원", "scene": "작은 정원", "mood": "따뜻함", "camera": "전경"},
        "pages": [
            {"page": page, "text": "하루가 물을 주어요.", "scene": f"화분에 물 주는 모습 {extra_text}",
             "mood": "기쁨", "camera": "전경", "characters_present": ["hero"]}
            for page in range(1, 5)
        ],
        "continuity": {"character_consistency_notes": "노란 멜빵바지", "style_notes_for_images": "수채화"},
    }


def anthropic_response(extra_text=""):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(story_payload(extra_text), ensure_ascii=False)}],
            "usage": {"input_tokens": 100, "output_tokens": 200}}


@pytest.mark.asyncio
async def test_budget_rejects_unknown_hosts_contract_changes_redirects_and_excess_requests(comparison):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://untrusted.example/steal"}, json={})

    budget = comparison.RequestBudget("anthropic", "claude-sonnet-5", 2, httpx.MockTransport(transport))
    payload = {"model": "claude-sonnet-5", "max_tokens": 4000}
    async with budget.client(timeout=120) as client:
        with pytest.raises(comparison.ComparisonError, match="CASE_REQUEST_LIMIT"):
            await client.post(budget.url, headers={}, json=payload)
        budget.begin_case(1)
        for url in ("https://untrusted.example/v1/messages", "http://api.anthropic.com/v1/messages",
                    "https://api.anthropic.com.evil.test/v1/messages", "https://api.anthropic.com/v1/messages?copy=1"):
            with pytest.raises(comparison.ComparisonError, match="HOST_OR_REQUEST_LIMIT"):
                await client.post(url, headers={"x-api-key": "inert-secret"}, json=payload)
        for changed in ({"max_tokens": 12001}, {"max_tokens": True}, {"model": "unknown-model"},
                        {"tools": [{"name": "external"}]}, {"stream": True}):
            with pytest.raises(comparison.ComparisonError, match="REQUEST_CONTRACT_LIMIT"):
                await client.post(budget.url, headers={}, json={**payload, **changed})
        assert requests == []
        response = await client.post(budget.url, headers={}, json=payload)
        assert response.status_code == 302
        assert len(requests) == 1  # Redirect destination is never visited.
        with pytest.raises(comparison.ComparisonError, match="CASE_REQUEST_LIMIT"):
            await client.post(budget.url, headers={}, json=payload)
        budget.begin_case(2)
        await client.post(budget.url, headers={}, json=payload)
        budget.begin_case(3)
        with pytest.raises(comparison.ComparisonError, match="HOST_OR_REQUEST_LIMIT"):
            await client.post(budget.url, headers={}, json=payload)
    assert len(requests) == 2
    assert all(metric["output_contract"]["native_schema"] is False for metric in budget.metrics)


@pytest.mark.asyncio
async def test_each_case_can_make_only_one_request_even_if_generation_regresses(comparison, monkeypatch):
    original = llm.call_story_generation
    requests = []

    async def accidentally_retrying_generator(spec):
        await original(spec)
        return await original(spec)

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=anthropic_response())

    monkeypatch.setattr(llm, "call_story_generation", accidentally_retrying_generator)
    report = await comparison.compare(
        {"ANTHROPIC_API_KEY": "inert-anthropic-secret"}, "claude-sonnet-5", [1, 2],
        comparison.ACCEPTANCE / "case-budget", transport=httpx.MockTransport(transport),
    )
    assert len(requests) == report["request_count"] == 2
    assert report["native_schema"] is True
    assert report["native_schema_request_count"] == 2
    assert [len(case["requests"]) for case in report["cases"]] == [1, 1]
    assert all(case["status"] == "failed" for case in report["cases"])
    assert not list((comparison.ACCEPTANCE / "case-budget").glob("case-[0-9].json"))


@pytest.mark.asyncio
async def test_invalid_keys_cases_and_output_paths_fail_before_network_or_env_file_changes(comparison, tmp_path):
    env_file = tmp_path / "inert.env"
    original = b"LLM_PROVIDER=anthropic\nLLM_API_KEY=inert-anthropic-secret\n"
    env_file.write_bytes(original)
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request))
    configured = {"ANTHROPIC_API_KEY": "inert-anthropic-secret"}
    invalid = [
        ({"LLM_PROVIDER": "openai", "LLM_API_KEY": "inert-openai-secret"}, [1], comparison.ACCEPTANCE / "wrong-provider"),
        ({"ANTHROPIC_API_KEY": "bad key\n"}, [1], comparison.ACCEPTANCE / "whitespace"),
        (configured, [1, 1], comparison.ACCEPTANCE / "duplicates"),
        (configured, list(range(1, 8)), comparison.ACCEPTANCE / "seven-cases"),
        (configured, [True], comparison.ACCEPTANCE / "boolean"),
        (configured, [1], tmp_path / "outside-acceptance"),
    ]
    for values, cases, output in invalid:
        with pytest.raises(comparison.ComparisonError):
            await comparison.compare(values, "claude-sonnet-5", cases, output, transport=transport)
        assert not output.exists()
    assert requests == []
    assert env_file.read_bytes() == original
    assert configured == {"ANTHROPIC_API_KEY": "inert-anthropic-secret"}


@pytest.mark.asyncio
async def test_secret_echo_and_arbitrary_exception_text_are_never_written(comparison, capsys):
    key = "inert-anthropic-secret-value"
    other_key = "inert-openai-secret-value"
    output = comparison.ACCEPTANCE / "secret-echo"
    report = await comparison.compare(
        {"ANTHROPIC_API_KEY": key, "OPENAI_API_KEY": other_key}, "claude-sonnet-5", [1], output,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=anthropic_response(other_key))),
    )
    assert report["cases"][0]["failure"] == "SECRET_IN_OUTPUT"
    assert not (output / "case-1.json").exists()
    assert str(comparison.ComparisonError(key)) == "COMPARISON_FAILED"
    artifacts = "".join(path.read_text() for path in output.glob("*.json"))
    captured = capsys.readouterr()
    for secret in (key, other_key):
        assert secret not in artifacts + captured.out + captured.err
    assert all(path.stat().st_mode & 0o077 == 0 for path in output.glob("*.json"))


@pytest.mark.asyncio
async def test_openai_shared_adapter_uses_same_guarded_transport_and_no_retention(comparison, monkeypatch):
    requests = []

    def forbid_unguarded_client(*args, **kwargs):
        pytest.fail("Shared OpenAI adapter bypassed comparison transport")

    monkeypatch.setattr(openai_contract, "httpx", SimpleNamespace(AsyncClient=forbid_unguarded_client))

    def transport(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert payload["store"] is False
        assert payload["model"] == "gpt-5.6-sol"
        assert 1 <= payload["max_output_tokens"] <= 12000
        assert request.headers["Authorization"] == "Bearer inert-openai-secret"
        assert openai_contract.httpx.TimeoutException is httpx.TimeoutException
        assert openai_contract.httpx.HTTPError is httpx.HTTPError
        return httpx.Response(200, json={
            "status": "completed", "output": [{"type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(story_payload(), ensure_ascii=False)}]}],
            "usage": {"input_tokens": 100, "output_tokens": 200},
        })

    report = await comparison.compare(
        {"OPENAI_API_KEY": "inert-openai-secret"}, "gpt-5.6-sol", [1], comparison.ACCEPTANCE / "openai-guard",
        transport=httpx.MockTransport(transport),
    )
    assert len(requests) == report["request_count"] == 1
    assert report["cases"][0]["status"] == "structurally_valid"
    assert report["native_schema"] is True
    assert report["output_contracts"][0]["protocol"] == "openai_responses"
    assert openai_contract.httpx.AsyncClient is forbid_unguarded_client
    requests.clear()

    def billing_denied(request):
        requests.append(request)
        return httpx.Response(402, json={"error": {"message": "private-provider-billing-detail"}})

    report = await comparison.compare(
        {"OPENAI_API_KEY": "inert-openai-secret"}, "gpt-5.6-sol", [1, 2, 3], comparison.ACCEPTANCE / "quota-stop",
        transport=httpx.MockTransport(billing_denied),
    )
    assert len(requests) == report["request_count"] == 1
    assert report["stopped_reason"] == "PROVIDER_ACCESS_OR_QUOTA"
    assert report["unstarted_cases"] == [2, 3]
    assert "private-provider-billing-detail" not in json.dumps(report)


@pytest.mark.asyncio
async def test_validation_diagnostics_keep_only_owned_fields_and_static_types(comparison, capsys):
    secret = "PRIVATE_CHILD_VALUE_AND_API_KEY"
    collector = comparison.ValidationDiagnostics()
    collector.schema(
        secret, schema_model="StoryDraft", context={secret: secret},
        schema_diagnostics=[
            {"field_path": "pages[].scene", "validation_type": "string_too_long", "input": secret, "message": secret},
            {"field_path": secret, "validation_type": "string_type"},
            {"field_path": "pages[].text", "validation_type": secret},
            {"field_path": f"pages[1].{secret}", "validation_type": "string_type"},
            {"field_path": [secret], "validation_type": {secret: secret}},
        ],
    )
    collector.schema(secret, schema_model=secret, schema_diagnostics=[
        {"field_path": "title", "validation_type": "string_type"},
    ])
    collector.integrity(
        secret, raw_output=secret, integrity_diagnostics=[
            {"field_path": "pages[].text", "rule": "invalid_unicode", "value": secret},
            {"field_path": "pages[].text", "rule": secret},
            {"field_path": secret, "rule": "invalid_unicode"},
        ],
    )
    assert collector.entries == [
        {"source": "schema", "field_path": "pages[].scene", "validation_type": "string_too_long"},
        {"source": "integrity", "field_path": "pages[].text", "rule": "invalid_unicode"},
    ]
    assert secret not in json.dumps(collector.entries)

    requests = []

    def transport(request):
        requests.append(request)
        payload = story_payload()
        if len(requests) == 1:
            payload["pages"][0]["scene"] = secret * 12
        else:
            payload["pages"][0]["text"] = "하루가 \ufffd 물을 주어요."
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
        ]})

    output = comparison.ACCEPTANCE / "private-diagnostics"
    report = await comparison.compare(
        {"ANTHROPIC_API_KEY": secret}, "claude-sonnet-5", [1, 2], output,
        transport=httpx.MockTransport(transport),
    )
    assert report["cases"][0]["validation_diagnostics"] == [
        {"source": "schema", "field_path": "pages[].scene", "validation_type": "string_too_long"},
    ]
    assert report["cases"][1]["validation_diagnostics"] == [
        {"source": "integrity", "field_path": "pages[].text", "rule": "invalid_unicode"},
    ]
    assert report["request_count"] == 2
    assert not list(output.glob("case-[0-9].json"))
    artifacts = "".join(path.read_text() for path in output.glob("*.json"))
    captured = capsys.readouterr()
    assert secret not in artifacts + captured.out + captured.err
    assert captured.out.splitlines() == ["Case 1: failed", "Case 2: failed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("anthropic", "claude-opus-5"), ("openai", "gpt-5.6-sol")])
async def test_schema_metadata_hashes_actual_owned_wire_schema_only(comparison, provider, model):
    from src.models.dto import StoryDraft
    from src.services.structured_output import provider_output_schema

    secret = "PRIVATE_PER_REQUEST_SCHEMA_VALUE"
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={})

    budget = comparison.RequestBudget(provider, model, 1, httpx.MockTransport(transport))
    schema = provider_output_schema(StoryDraft.model_json_schema(), provider=provider)
    output_format = {"type": "json_schema", "schema": schema}
    if provider == "anthropic":
        payload = {"model": model, "max_tokens": 4000, "output_config": {"format": output_format}}
    else:
        output_format.update(name="story_draft", strict=True)
        payload = {"model": model, "max_output_tokens": 8192, "store": False, "text": {"format": output_format}}
    budget.begin_case(1)
    async with budget.client(timeout=120) as client:
        schema["properties"]["title"]["description"] = secret
        with pytest.raises(comparison.ComparisonError, match="REQUEST_CONTRACT_LIMIT"):
            await client.post(budget.url, headers={}, json=payload)
        assert requests == [] and budget.metrics == []
        del schema["properties"]["title"]["description"]
        await client.post(budget.url, headers={}, json=payload)
    captured = requests[0]["output_config" if provider == "anthropic" else "text"]["format"]["schema"]
    expected_hash = hashlib.sha256(json.dumps(captured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    contract = budget.metrics[0]["output_contract"]
    assert contract == {
        "protocol": "anthropic_messages" if provider == "anthropic" else "openai_responses",
        "format": "json_schema", "native_schema": True, "schema_model": "StoryDraft",
        "schema_sha256": expected_hash, "schema_hash_encoding": "json-sort-keys-compact-utf8",
    }
    assert secret not in json.dumps(budget.metrics)
