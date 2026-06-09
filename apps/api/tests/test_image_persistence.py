"""이미지 영속화 회귀 — provider 임시 URL을 그대로 저장하지 않고 S3로 재업로드하는지.

critical: openai/replicate/fal이 돌려주는 만료성 URL을 DB에 그대로 저장하면 수 시간 뒤
모든 책 이미지가 404가 된다. 본 테스트는 각 provider 경로가 S3 영속 URL을 반환함을 보장.
"""

import base64

import pytest

import src.services.image as image_mod
from src.core.config import settings
from src.core.errors import ImageError
from src.models.dto import ImagePrompt


def _prompt():
    return ImagePrompt(
        page=1,
        positive_prompt="a brave little rabbit in a forest",
        negative_prompt="text, watermark, letters",
        seed=42,
        aspect_ratio="3:4",
    )


class _FakeResp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code = status
        self._json = json_data or {}
        self.content = content
        self.headers = {"content-type": "image/png"}
        self.text = ""

    def json(self):
        return self._json


async def _noop_sleep(*_a, **_k):
    return None


@pytest.mark.asyncio
async def test_openai_persists_b64_and_skips_response_format_for_gpt_image(monkeypatch):
    monkeypatch.setattr(settings, "image_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model", "gpt-image-1")
    raw_bytes = b"\x89PNG-fake-bytes"
    sent = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent["json"] = json
            return _FakeResp(200, {"data": [{"b64_json": base64.b64encode(raw_bytes).decode()}]})

    monkeypatch.setattr(image_mod.httpx, "AsyncClient", _Client)

    uploaded = {}

    async def _fake_upload(data, key, content_type="image/png"):
        uploaded["data"] = data
        uploaded["key"] = key
        return f"https://s3.example.com/{key}"

    from src.services import storage as storage_mod

    monkeypatch.setattr(storage_mod.storage_service, "upload_bytes", _fake_upload)

    url = await image_mod._generate_openai(_prompt())

    # gpt-image-1엔 response_format/quality 미전송(거부 파라미터)
    assert "response_format" not in sent["json"]
    assert "quality" not in sent["json"]
    # 결과가 S3 영속 URL(provider 임시 URL 아님) + 디코드된 바이트가 업로드됨
    assert url.startswith("https://s3.example.com/images/openai/")
    assert uploaded["data"] == raw_bytes


@pytest.mark.asyncio
async def test_openai_dalle_requests_b64_json(monkeypatch):
    monkeypatch.setattr(settings, "image_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model", "dall-e-3")
    sent = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent["json"] = json
            return _FakeResp(200, {"data": [{"b64_json": base64.b64encode(b"x").decode()}]})

    monkeypatch.setattr(image_mod.httpx, "AsyncClient", _Client)

    async def _fake_upload(data, key, content_type="image/png"):
        return f"https://s3.example.com/{key}"

    from src.services import storage as storage_mod

    monkeypatch.setattr(storage_mod.storage_service, "upload_bytes", _fake_upload)

    await image_mod._generate_openai(_prompt())
    # dall-e-3는 b64_json 명시 요청(URL 만료 회피)
    assert sent["json"]["response_format"] == "b64_json"


@pytest.mark.asyncio
async def test_replicate_persists_external_url(monkeypatch):
    monkeypatch.setattr(settings, "image_api_key", "test-key")
    monkeypatch.setattr(image_mod.asyncio, "sleep", _noop_sleep)
    captured = {}

    async def _fake_persist(url, provider, page):
        captured.update(url=url, provider=provider)
        return f"https://s3.example.com/images/{provider}/abc.png"

    monkeypatch.setattr(image_mod, "_persist_external_url", _fake_persist)

    raw = "https://pbxt.replicate.delivery/abc.png"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _FakeResp(201, {"id": "pred1"})

        async def get(self, *a, **k):
            return _FakeResp(200, {"status": "succeeded", "output": [raw]})

    monkeypatch.setattr(image_mod.httpx, "AsyncClient", _Client)

    url = await image_mod._generate_replicate(_prompt())
    assert captured["url"] == raw and captured["provider"] == "replicate"
    assert url.startswith("https://s3.example.com/images/replicate/")


@pytest.mark.asyncio
async def test_fal_persists_external_url(monkeypatch):
    monkeypatch.setattr(settings, "image_api_key", "test-key")
    captured = {}

    async def _fake_persist(url, provider, page):
        captured.update(url=url, provider=provider)
        return f"https://s3.example.com/images/{provider}/abc.png"

    monkeypatch.setattr(image_mod, "_persist_external_url", _fake_persist)

    raw = "https://fal.media/files/abc.png"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _FakeResp(200, {"images": [{"url": raw}]})

    monkeypatch.setattr(image_mod.httpx, "AsyncClient", _Client)

    url = await image_mod._generate_fal(_prompt())
    assert captured["url"] == raw and captured["provider"] == "fal"
    assert url.startswith("https://s3.example.com/images/fal/")


@pytest.mark.asyncio
async def test_persist_external_url_blocks_ssrf(monkeypatch):
    # 사설/비허용 도메인은 SSRF 가드로 차단(다운로드 시도 안 함)
    with pytest.raises(ImageError):
        await image_mod._persist_external_url("http://169.254.169.254/latest/meta-data", "x", 1)


@pytest.mark.asyncio
async def test_mock_provider_stays_external(monkeypatch):
    # mock은 picsum URL을 그대로 — 오프라인 테스트가 S3 없이 동작해야 하므로 영속화 제외
    monkeypatch.setattr(settings, "image_provider", "mock")
    url = await image_mod.generate_image(_prompt())
    assert "picsum.photos" in url
