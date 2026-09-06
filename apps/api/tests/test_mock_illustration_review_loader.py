"""The mock runtime hook cannot become a live-provider quality bypass."""

import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from src.core.errors import LLMError
from src.services import image_quality


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "mock_review_loader", ROOT / "scripts/mock_illustration_review.py"
)
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


@pytest.fixture
def mock_review(monkeypatch):
    monkeypatch.setenv(loader.MARKER_NAME, loader.MARKER_VALUE)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("ILLUSTRATION_QUALITY_ENABLED", "false")
    monkeypatch.setattr(image_quality.settings, "testing", False)
    monkeypatch.setattr(image_quality.settings, "llm_provider", "mock")
    monkeypatch.setattr(image_quality.settings, "image_provider", "mock")
    monkeypatch.setattr(image_quality.settings, "illustration_quality_enabled", True)
    # Undo only the two permitted adapter replacements after each test.
    monkeypatch.setattr(image_quality, "review_provider_configured", image_quality.review_provider_configured)
    monkeypatch.setattr(image_quality, "review_book_illustrations", image_quality.review_book_illustrations)

    async def no_provider(**kwargs):
        pytest.fail("A disposable mock review must never call a provider")

    monkeypatch.setattr(image_quality, "request_openai_json", no_provider)
    loader.install()
    return image_quality


def review_inputs(count=5):
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="PNG")
    return {
        "title": "작은 정원",
        "page_texts": {number: "함께 꽃에 물을 주었어요." for number in range(count)},
        "image_prompts": {number: "A rabbit waters a garden" for number in range(count)},
        "images": {number: (stream.getvalue(), "image/png") for number in range(count)},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [5, 9, 13])
async def test_mock_review_validates_and_explicitly_reports_every_page(mock_review, count):
    review = await mock_review.review_book_illustrations(**review_inputs(count))
    assert isinstance(review, image_quality.BookIllustrationReview)
    assert [page.page_number for page in review.pages] == list(range(count))
    assert all(page.issues == [] for page in review.pages)
    assert mock_review.review_provider_configured()
    assert os.environ["ILLUSTRATION_QUALITY_ENABLED"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing_page", "bad_bytes", "wrong_mime"])
async def test_mock_review_keeps_real_input_validation(mock_review, damage):
    inputs = review_inputs()
    if damage == "missing_page":
        inputs["images"].pop(2)
    elif damage == "bad_bytes":
        inputs["images"][2] = (b"not an image", "image/png")
    else:
        inputs["images"][2] = (inputs["images"][2][0], "image/jpeg")
    with pytest.raises(LLMError):
        await mock_review.review_book_illustrations(**inputs)


@pytest.mark.parametrize("field,value", [
    (loader.MARKER_NAME, ""),
    (loader.MARKER_NAME, "unrelated-qa"),
    ("LLM_PROVIDER", "openai"),
    ("IMAGE_PROVIDER", "gemini"),
])
def test_installer_refuses_missing_marker_or_any_live_provider(monkeypatch, field, value):
    monkeypatch.setenv(loader.MARKER_NAME, loader.MARKER_VALUE)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv(field, value)
    before = (image_quality.review_provider_configured, image_quality.review_book_illustrations)
    with pytest.raises(RuntimeError, match="MOCK_QA_CONFIGURATION_REQUIRED"):
        loader.install()
    assert before == (image_quality.review_provider_configured, image_quality.review_book_illustrations)


@pytest.mark.asyncio
async def test_live_provider_change_after_install_fails_closed(mock_review, monkeypatch):
    monkeypatch.setattr(mock_review.settings, "llm_provider", "openai")
    assert not mock_review.review_provider_configured()
    with pytest.raises(RuntimeError, match="MOCK_QA_CONFIGURATION_REQUIRED"):
        await mock_review.review_book_illustrations(**review_inputs())


def child_env(startup, **overrides):
    env = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR") if name in os.environ}
    env.update({
        "PYTHONPATH": os.pathsep.join((str(startup), str(ROOT / "apps/api"))),
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "TESTING": "false", "LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "mock",
        "ILLUSTRATION_QUALITY_ENABLED": "false", loader.MARKER_NAME: loader.MARKER_VALUE,
    })
    env.update(overrides)
    return env


def test_sitecustomize_defers_settings_and_does_not_patch_pytest(tmp_path):
    loader.write_startup_loader(tmp_path)
    code = """import os, sys
assert 'src.core.config' not in sys.modules
os.environ['TESTING'] = 'true'
os.environ['ILLUSTRATION_QUALITY_ENABLED'] = 'false'
from src.services import image_quality
assert image_quality.settings.testing
assert image_quality.review_book_illustrations.__module__ == 'src.services.image_quality'
assert not image_quality.review_provider_configured()
print('UNPATCHED_PYTEST')
"""
    result = subprocess.run([sys.executable, "-c", code], env=child_env(tmp_path),
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "UNPATCHED_PYTEST" in result.stdout


def test_sitecustomize_installs_in_disposable_worker_process(tmp_path):
    loader.write_startup_loader(tmp_path)
    code = """import asyncio, json
from io import BytesIO
from PIL import Image
from src.services import image_quality
assert image_quality.settings.illustration_quality_enabled
assert image_quality.review_provider_configured()
async def forbidden(**kwargs):
    raise AssertionError('Provider request must not occur')
image_quality.request_openai_json = forbidden
data = BytesIO()
Image.new('RGB', (2, 2), 'white').save(data, format='PNG')
result = asyncio.run(image_quality.review_book_illustrations(
    title='Test garden', page_texts={n: 'A rabbit waters a flower.' for n in range(5)},
    image_prompts={n: 'A rabbit in a garden' for n in range(5)},
    images={n: (data.getvalue(), 'image/png') for n in range(5)}))
print(json.dumps(result.model_dump()))
"""
    result = subprocess.run([sys.executable, "-c", code], env=child_env(tmp_path),
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    pages = json.loads(result.stdout.strip().splitlines()[-1])["pages"]
    assert pages == [{"page_number": number, "issues": []} for number in range(5)]


def test_sitecustomize_rejection_stops_python_before_application(tmp_path):
    loader.write_startup_loader(tmp_path)
    result = subprocess.run([sys.executable, "-c", "print('APPLICATION_STARTED')"],
                            env=child_env(tmp_path, LLM_PROVIDER="openai"), cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "APPLICATION_STARTED" not in result.stdout
    assert "Mock QA startup rejected its configuration." in result.stderr
