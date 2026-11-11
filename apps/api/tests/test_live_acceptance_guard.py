"""The opt-in live gate cannot exceed its HTTP budget or journal private payloads."""

import importlib.util
import json
import stat
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


spec = importlib.util.spec_from_file_location(
    "live_guard", Path(__file__).resolve().parents[3] / "scripts/live_acceptance_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.asyncio
async def test_pilot_budget_covers_multiple_books_and_rolls_at_korean_midnight(
    tmp_path, monkeypatch,
):
    from datetime import timezone

    monkeypatch.setitem(sys.modules, "live_acceptance_guard", guard)
    entry_spec = importlib.util.spec_from_file_location(
        "pilot_entry", Path(spec.origin).with_name("pilot_provider_guard_entry.py"),
    )
    entry = importlib.util.module_from_spec(entry_spec)
    entry_spec.loader.exec_module(entry)
    base = tmp_path / "usage.jsonl"
    for key, value in {
        "LIVE_ACCEPTANCE_JOURNAL": str(base),
        "DAILY_GENERATION_BUDGET": "2",
        "ILLUSTRATION_QUALITY_ENABLED": "true",
        "LIVE_ACCEPTANCE_PAGE_COUNT": "4",
        "LLM_PROVIDER": "openai",
        "LLM_MODEL": "gpt-5.6-sol",
        "IMAGE_MODEL": "gpt-image-2",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(httpx.AsyncClient, "post", httpx.AsyncClient.post)
    now = datetime(2026, 11, 10, 14, 59, tzinfo=timezone.utc)
    entry.install_daily_guard(now=lambda tz: now.astimezone(tz))
    calls = 0

    def handle(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"usage": {"input_tokens": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        url = "https://api.openai.com/v1/images/generations"
        payload = {"model": "gpt-image-2", "n": 1, "quality": "low", "size": "1024x768"}
        for _ in range(32):
            assert (await client.post(url, json=payload)).status_code == 200
        with pytest.raises(RuntimeError, match="REQUEST_LIMIT"):
            await client.post(url, json=payload)
        assert calls == 32
        now = now.replace(hour=15, minute=0)
        with pytest.raises(RuntimeError, match="IMAGE_OPTIONS"):
            await client.post(url, json=dict(payload, n=2))
        assert (await client.post(url, json=payload)).status_code == 200
    assert calls == 33
    old = base.with_suffix(".20261110.jsonl")
    new = base.with_suffix(".20261111.jsonl")
    assert len(old.read_text().splitlines()) == 64
    assert len(new.read_text().splitlines()) == 2
    assert stat.S_IMODE(new.stat().st_mode) == 0o600


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    path.touch(mode=0o600)
    monkeypatch.setenv("LIVE_ACCEPTANCE_JOURNAL", str(path))
    monkeypatch.setenv("IMAGE_MODEL", "gemini-3-pro-image")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ILLUSTRATION_QUALITY_ENABLED", "false")
    monkeypatch.setenv("LIVE_ACCEPTANCE_PAGE_COUNT", "8")
    # Register the original descriptor with monkeypatch so installation is undone.
    monkeypatch.setattr(httpx.AsyncClient, "post", httpx.AsyncClient.post)
    guard.install()
    return path


@pytest.mark.asyncio
async def test_failed_requests_are_reserved_and_shared_across_clients(journal):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "private-server-body"})
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image:generateContent"
    for _ in range(9):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await client.post(url, json={})).status_code == 429
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="REQUEST_LIMIT"):
            await client.post(url, json={})
    assert len(calls) == 9
    assert "private-server-body" not in journal.read_text()


@pytest.mark.asyncio
async def test_journal_keeps_only_numeric_usage_and_excludes_credentials(journal):
    sentinel = "private-credential-and-child-data"
    def handler(request):
        return httpx.Response(200, json={"content": sentinel, "usage": {
            "input_tokens": 10, "output_tokens": 20, "untrusted": sentinel}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": sentinel},
                          json={"model": "claude-sonnet-5", "max_tokens": 500, "messages": sentinel})
    raw = journal.read_text()
    assert sentinel not in raw
    event = json.loads(raw.splitlines()[1])
    assert event["usage"] == {"input_tokens": 10, "output_tokens": 20}


@pytest.mark.asyncio
@pytest.mark.parametrize("url,tokens", [
    ("https://untrusted.example/messages", 500),
    ("https://api.anthropic.com/v1/messages?api_key=secret", 500),
    ("https://api.anthropic.com/v1/messages", 8001),
])
async def test_unexpected_host_query_or_output_limit_never_reaches_network(journal, url, tokens):
    def handler(_request):
        pytest.fail("No HTTP request should occur")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="LIVE_ACCEPTANCE"):
            await client.post(url, json={"model": "claude-sonnet-5", "max_tokens": tokens})
    assert journal.read_text() == ""


@pytest.fixture
def openai_journal(tmp_path, monkeypatch):
    path = tmp_path / "openai-usage.jsonl"
    path.touch(mode=0o600)
    monkeypatch.setenv("LIVE_ACCEPTANCE_JOURNAL", str(path))
    monkeypatch.setenv("IMAGE_MODEL", "gemini-3-pro-image")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("ILLUSTRATION_QUALITY_ENABLED", "false")
    monkeypatch.setenv("LIVE_ACCEPTANCE_PAGE_COUNT", "8")
    monkeypatch.setattr(httpx.AsyncClient, "post", httpx.AsyncClient.post)
    guard.install()
    return path


@pytest.mark.asyncio
async def test_openai_reservations_cover_failed_requests_and_numeric_usage(openai_journal):
    calls = []
    sentinel = "private-provider-key-and-child-data"

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": sentinel, "usage": {
            "input_tokens": 10, "output_tokens": 20, "detail": sentinel}})

    payload = {"model": "gpt-5.6-sol", "max_output_tokens": 16000, "store": False}
    for _ in range(16):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await client.post("https://api.openai.com/v1/responses", json=payload)).status_code == 429
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="REQUEST_LIMIT"):
            await client.post("https://api.openai.com/v1/responses", json=payload)
    assert len(calls) == 16
    raw = openai_journal.read_text()
    assert sentinel not in raw
    event = json.loads(raw.splitlines()[1])
    assert event["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert (event["provider"], event["model"]) == ("openai", "gpt-5.6-sol")


@pytest.mark.asyncio
@pytest.mark.parametrize("url,changes,options", [
    ("https://api.openai.com/v1/chat/completions", {}, {}),
    ("https://api.openai.com/v1/responses", {"model": "gpt-6-astra"}, {}),
    ("https://api.openai.com/v1/responses", {"model": "gpt-5.6-sol-other"}, {}),
    ("https://api.openai.com/v1/responses", {"max_output_tokens": 16001}, {}),
    ("https://api.openai.com/v1/responses", {"max_output_tokens": None}, {}),
    ("https://api.openai.com/v1/responses", {"max_output_tokens": True}, {}),
    ("https://api.openai.com/v1/responses", {"store": True}, {}),
    ("https://api.openai.com/v1/responses", {"store": None}, {}),
    ("https://api.openai.com/v1/responses", {"service_tier": "priority"}, {}),
    ("https://api.openai.com/v1/responses", {}, {"params": {"api_key": "private-key"}}),
    ("https://api.openai.com/v1/responses", {}, {"follow_redirects": True}),
])
async def test_openai_same_host_wrong_route_model_or_budget_is_blocked(
    openai_journal, url, changes, options,
):
    def handler(_request):
        pytest.fail("Rejected requests must not reach the provider")

    payload = {"model": "gpt-5.6-sol", "max_output_tokens": 1000, "store": False, **changes}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="LIVE_ACCEPTANCE"):
            await client.post(url, json=payload, **options)
    assert openai_journal.read_text() == ""


@pytest.fixture
def acceptance_scripts(monkeypatch):
    # Importing these entrypoints performs no configuration reads or live work.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import run_live_book_acceptance
    import run_live_quality_matrix
    return run_live_book_acceptance, run_live_quality_matrix


@pytest.mark.parametrize("page_count,reader_profile_file", [(8, None), (12, "private.json")])
def test_paid_first_book_trial_requires_a_fictional_twelve_page_run(
    acceptance_scripts, page_count, reader_profile_file,
):
    book, _ = acceptance_scripts
    args = SimpleNamespace(
        page_count=page_count, first_book_trial=True,
        reader_profile_file=Path(reader_profile_file) if reader_profile_file else None,
    )
    with pytest.raises(book.GateFailure, match="TRIAL_REQUIRES_FICTIONAL_TWELVE_PAGE_RUN"):
        book.run_acceptance(args)


def test_explicit_llm_file_is_separate_and_does_not_modify_base_env(tmp_path, acceptance_scripts):
    book, _ = acceptance_scripts
    base = tmp_path / "synthetic.env"
    separate = tmp_path / "synthetic-openai.env"
    base_content = ("LLM_PROVIDER=anthropic\nLLM_MODEL=claude-sonnet-5\n"
                    "LLM_API_KEY=inert-anthropic\nIMAGE_PROVIDER=gemini\n"
                    "IMAGE_MODEL=gemini-3-pro-image\nIMAGE_API_KEY=inert-image\n")
    base.write_text(base_content)
    separate.write_text("OPENAI_API_KEY=inert-openai\n")
    args = SimpleNamespace(env_file=base, llm_env_file=separate,
                           llm_model="gpt-5.6-sol", image_model=None)
    config = book.load_runtime_config(args)
    assert (config.llm_provider, config.llm_api_key, config.image_api_key) == (
        "openai", "inert-openai", "inert-image")
    assert base.read_text() == base_content
    assert separate.read_text() == "OPENAI_API_KEY=inert-openai\n"
    args.llm_env_file = None
    with pytest.raises(book.GateFailure, match="INVALID_PROVIDER_KEY"):
        book.load_runtime_config(args)


@pytest.mark.parametrize("provider,model", [
    ("openai", "gpt-5.6"), ("openai", "gpt-5.6-sol-other"),
    ("openai", "claude-sonnet-5"), ("anthropic", "claude-sonnet-5-20260901"),
])
def test_unverified_or_mismatched_model_selection_fails_before_install(provider, model):
    with pytest.raises(RuntimeError, match="INVALID_MODEL_SELECTION"):
        guard.validate_selection(provider, model, "gemini-3-pro-image")


def write_cost_fixture(directory, provider="openai", model="gpt-5.6-sol", image="gemini-3-pro-image"):
    result = {"providers": {"llm": provider, "image": "gemini"},
              "models": {"llm": model, "image": image},
              "images": [{"width": 896, "height": 1200}]}
    events = [
        {"kind": "response", "role": "llm", "http_status": 200,
         "provider": provider, "model": model,
         "usage": {"input_tokens": 1000, "output_tokens": 2000}},
        {"kind": "response", "role": "image", "http_status": 200,
         "provider": "gemini", "model": image,
         "usage": {"promptTokenCount": 1000, "candidatesTokenCount": 1200, "thoughtsTokenCount": 20}},
    ]
    (directory / "result.json").write_text(json.dumps(result))
    (directory / "provider-usage.jsonl").write_text("\n".join(map(json.dumps, events)))
    return result, events


@pytest.mark.parametrize("provider,model,text_expected", [
    ("anthropic", "claude-sonnet-5", 0.022),
    ("anthropic", "claude-opus-5", 0.055),
    ("openai", "gpt-6-astra", 0.11),
    ("openai", "gpt-5.6-sol", 0.044),
])
@pytest.mark.parametrize("image,image_expected", [
    ("gemini-3-pro-image", 0.1376), ("gemini-3.1-flash-image", 0.068),
])
def test_cost_estimate_uses_the_recorded_model_and_provider(
    tmp_path, acceptance_scripts, provider, model, text_expected, image, image_expected,
):
    _, matrix = acceptance_scripts
    write_cost_fixture(tmp_path, provider, model, image)
    text_cost, image_cost = matrix.costs(tmp_path)
    assert text_cost == pytest.approx(text_expected)
    assert image_cost == pytest.approx(image_expected)


@pytest.mark.parametrize("failure", ["unknown_model", "wrong_provider", "unknown_dimensions", "missing_usage"])
def test_unknown_cost_inputs_fail_closed(tmp_path, acceptance_scripts, failure):
    _, matrix = acceptance_scripts
    result, events = write_cost_fixture(tmp_path)
    if failure == "unknown_model":
        result["models"]["llm"] = "gpt-unverified"
    elif failure == "wrong_provider":
        result["providers"]["llm"] = "anthropic"
    elif failure == "unknown_dimensions":
        result["images"][0]["width"] = 900
    else:
        events[0]["usage"] = {}
    (tmp_path / "result.json").write_text(json.dumps(result))
    (tmp_path / "provider-usage.jsonl").write_text("\n".join(map(json.dumps, events)))
    with pytest.raises(RuntimeError, match="COST_"):
        matrix.costs(tmp_path)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1", "10.01", "unbounded"])
def test_matrix_rejects_spend_thresholds_that_disable_the_paid_guard(acceptance_scripts, value):
    import argparse

    _, matrix = acceptance_scripts
    with pytest.raises(argparse.ArgumentTypeError):
        matrix.text_spend_threshold(value)


def test_current_openai_image_config(acceptance_scripts):
    book, _ = acceptance_scripts
    values = dict(LLM_PROVIDER='openai', LLM_MODEL='gpt-5.6-sol', LLM_API_KEY='inert',
                  IMAGE_PROVIDER='openai', IMAGE_MODEL='gpt-image-2', IMAGE_API_KEY='inert-image')
    assert book.runtime_config(values).image_provider == 'openai'
    with pytest.raises(book.GateFailure, match='INVALID_IMAGE_CONFIGURATION'):
        book.runtime_config(dict(values, IMAGE_PROVIDER='gemini'))


@pytest.mark.asyncio
async def test_openai_images_share_budget_for_generation_edits_and_failures(tmp_path, monkeypatch):
    path = tmp_path / 'journal.jsonl'
    path.touch()
    for key, value in dict(LIVE_ACCEPTANCE_JOURNAL=str(path), IMAGE_MODEL='gpt-image-2',
                           LLM_PROVIDER='openai', LLM_MODEL='gpt-5.6-sol',
                           ILLUSTRATION_QUALITY_ENABLED='true', LIVE_ACCEPTANCE_PAGE_COUNT='4').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(httpx.AsyncClient, 'post', httpx.AsyncClient.post)
    guard.install()
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={'private': 'sentinel-private', 'usage': {'input_tokens': 5}})
    payload = dict(model='gpt-image-2', n=1, size='768x1024', quality='medium', prompt='sentinel-private')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for n in range(7):
            if n % 2:
                await client.post('https://api.openai.com/v1/images/edits',
                                  data={k: str(v) for k, v in payload.items()},
                                  files={'image[]': ('reference.png', b'sentinel-private', 'image/png')})
            else:
                await client.post('https://api.openai.com/v1/images/generations', json=payload)
        with pytest.raises(RuntimeError, match='REQUEST_LIMIT'):
            await client.post('https://api.openai.com/v1/images/generations', json=payload)
        for field, value in [('n', 2), ('n', True), ('quality', 'auto'), ('size', 'auto'), ('model', 'other')]:
            with pytest.raises(RuntimeError, match='IMAGE_OPTIONS|MODEL_MISMATCH'):
                await client.post('https://api.openai.com/v1/images/generations', json=dict(payload, **{field: value}))
    assert len(requests) == 7
    assert 'sentinel-private' not in path.read_text()
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(e['provider'] == 'openai' for e in events)
    assert events[1]['usage'] == {'input_tokens': 5}


def test_openai_image_dimensions_are_measured_from_returned_bytes():
    import base64
    from io import BytesIO
    from PIL import Image
    stream = BytesIO()
    Image.new('RGB', (12, 16)).save(stream, format='PNG')
    body = {'data': [{'b64_json': base64.b64encode(stream.getvalue()).decode()}]}
    assert guard.image_dimensions(body) == ([{'width': 12, 'height': 16}], True)
    assert guard.image_dimensions({'data': [{'url': 'https://example.invalid'}]}) == ([], False)


def test_only_provider_observation_gap_allows_fresh_candidate(acceptance_scripts):
    book, _ = acceptance_scripts
    services = {name: 'healthy' for name in ('database', 'redis', 'job_monitor', 'storage', 'provider_keys')}
    services.update(provider_runtime='unverified', cost_budget='configured')
    assert book.unverified_candidate_readiness(503, {'services': services})
    for name in services:
        assert not book.unverified_candidate_readiness(503, {'services': dict(services, **{name: 'unhealthy'})})
    assert not book.unverified_candidate_readiness(500, {'services': services})
    assert not book.unverified_candidate_readiness(503, {})
