"""The mock runtime hook cannot become a live-provider quality bypass."""

import importlib.util
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

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


@pytest.mark.skipif(os.name != 'posix', reason='local review uses POSIX private files')
def test_review_invite_file_is_live_and_fail_closed(tmp_path):
    loader.write_startup_loader(tmp_path)
    invite_file = tmp_path / 'invitations.txt'
    invite_file.touch(mode=0o600)
    code = """import os
from pathlib import Path
from src.core.generation_access import generation_access_allowed, generation_identity_hash

path = Path(os.environ['STORYBOOK_LOCAL_REVIEW_INVITATIONS_FILE'])
owner, other = 'synthetic-review-owner', 'another-synthetic-account'
assert not generation_access_allowed(owner)
path.write_text(generation_identity_hash(owner) + '\\n')
assert generation_access_allowed(owner) and not generation_access_allowed(other)
path.chmod(0o644)
assert not generation_access_allowed(owner)
path.chmod(0o600)
with path.open('a') as invites:
    invites.write('invalid\\n')
assert not generation_access_allowed(owner)
path.write_text(generation_identity_hash(owner) + '\\n')
saved = path.with_suffix('.saved')
path.rename(saved)
path.symlink_to(saved)
assert not generation_access_allowed(owner)
"""
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env=child_env(tmp_path, FREE_PLAN_FIRST_BOOK_TRIAL='true',
                                          GENERATION_ACCESS_MODE='invite_only',
                                          **{loader.REVIEW_INVITATIONS_ENV: str(invite_file)}),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_sitecustomize_rejection_stops_python_before_application(tmp_path):
    loader.write_startup_loader(tmp_path)
    result = subprocess.run([sys.executable, "-c", "print('APPLICATION_STARTED')"],
                            env=child_env(tmp_path, LLM_PROVIDER="openai"), cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "APPLICATION_STARTED" not in result.stdout
    assert "Mock QA startup rejected its configuration." in result.stderr


def test_realtime_review_rejects_any_nonfixture_key(tmp_path):
    loader.write_startup_loader(tmp_path)
    (tmp_path / 'replay_review_archive.py').write_bytes((ROOT / 'scripts/replay_review_archive.py').read_bytes())
    result = subprocess.run(
        [sys.executable, '-c', "print('APPLICATION_STARTED')"], cwd=tmp_path,
        env=child_env(tmp_path, STORYBOOK_LOCAL_REVIEW_ARCHIVE=str(tmp_path),
                      TTS_PROVIDER='openai_realtime', OPENAI_TTS_API_KEY='incorrect-test-value'),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert 'APPLICATION_STARTED' not in result.stdout
    assert 'Mock QA startup rejected its configuration.' in result.stderr


@pytest.mark.parametrize(('provider', 'fault'), [
    (provider, fault) for provider in ('gemini', 'realtime')
    for fault in (None, 'child_data', 'text', 'audio')
] + [('realtime', 'wav_format'), ('realtime', 'wrong_title')])
def test_review_archive_copies_only_verified_fictional_media(tmp_path, provider, fault):
    archive_spec = importlib.util.spec_from_file_location(
        'review_archive_loader', ROOT / 'scripts/replay_review_archive.py',
    )
    replay = importlib.util.module_from_spec(archive_spec)
    archive_spec.loader.exec_module(replay)
    clips_dir = tmp_path / 'review-audio'
    clips_dir.mkdir()
    pages = [{'page_number': page, 'text': f'Synthetic page {page}'} for page in range(1, 13)]
    if provider == 'realtime':
        buffer = BytesIO()
        with wave.open(buffer, 'wb') as audio:
            audio.setparams((1, 2, 16000 if fault == 'wav_format' else 24000, 0, 'NONE', ''))
            audio.writeframes(b'\0\0' * 240)
        clip_bytes = buffer.getvalue()
        extension = 'wav'
    else:
        clip_bytes = b'fictional audio bytes'
        extension = 'mp3'
    clips = [{'page': page['page_number'],
              'input_sha256': hashlib.sha256(page['text'].encode()).hexdigest(),
              'sha256': hashlib.sha256(clip_bytes).hexdigest()} for page in pages]
    if fault == 'text':
        pages[0]['text'] = 'Different text'
    (tmp_path/'book.json').write_text(json.dumps({'book_id':'fixture','title':'Fixture book', 'language':'ko',
        'target_age':'7-9','style':'watercolor','pages':pages,'cover_image_url':'do not copy'}))
    (tmp_path/'result.json').write_text(json.dumps({'book_id':'fixture','status':'passed',
        'real_child_data':fault == 'child_data','data_scope':{'photos_used':False,'appearance':'fictional_fixture'}}))
    if provider == 'realtime':
        (clips_dir/'verification.json').write_text(json.dumps({
            'status': 'FULL_BOOK_GENERATED_WITH_TARGETED_RECOVERY', 'synthesis_passed': 12, 'failures': [],
            'title': 'Wrong book' if fault == 'wrong_title' else 'Fixture book', 'age': '7-9',
            'provider': 'OpenAI Realtime', 'style': 'animated', 'voice': 'coral', 'per_page': clips,
        }))
    else:
        (clips_dir/'result.json').write_text(json.dumps({'status':'passed','fictional':True,
            'provider':'google_gemini','style':'animated','voice':'Kore','clips':clips}))
    for page in range(13):
        (tmp_path/f'page-{page:02d}.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        if page:
            (clips_dir/f'page-{page:02d}.{extension}').write_bytes(b'altered' if fault == 'audio' else clip_bytes)
    destination = tmp_path/'staged'
    realtime_audio = clips_dir if provider == 'realtime' else None
    if fault:
        with pytest.raises(ValueError):
            replay.stage_review_archive(tmp_path, destination, realtime_audio)
    else:
        replay.stage_review_archive(tmp_path, destination, realtime_audio)
        assert json.loads((destination/'story.json').read_text()) == {
            'title':'Fixture book', 'texts':[page['text'] for page in pages],
        }
        assert len(list(destination.glob('page-*.png'))) == 13
        assert len(list(destination.glob(f'page-*.{extension}'))) == 12
