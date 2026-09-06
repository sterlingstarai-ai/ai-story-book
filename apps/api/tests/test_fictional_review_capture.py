"""Fictional-only pre-QA evidence survives failures and restores exact inputs."""

from io import BytesIO
import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError
from src.services.image_quality import BookIllustrationReview


@pytest.fixture
def capture(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import fictional_review_capture

    root = tmp_path / "repository"
    root.mkdir(mode=0o700)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text("evidence/\n")
    directory = root / "evidence"
    directory.mkdir(mode=0o700)
    return fictional_review_capture, root, directory


def inputs():
    image = BytesIO()
    Image.new("RGB", (32, 32), "blue").save(image, format="PNG")
    return dict(title="가상 정원", page_texts={n: "가상 인물이 정원에서 웃고 있어요." for n in range(13)},
                image_prompts={n: "An invented character in a watercolor garden." for n in range(13)},
                images={n: (image.getvalue(), "image/png") for n in range(13)})


def review():
    return BookIllustrationReview(pages=[{"page_number": n, "issues": ["action_mismatch"] if n in (1, 5, 12) else []}
                                        for n in range(13)])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_failed", [False, True])
async def test_all_thirteen_inputs_are_saved_before_request_and_survive_review_failure(capture, provider_failed):
    module, root, directory = capture
    source = inputs()
    sentinel = "private-provider-error-body-and-auth-key"

    async def provider(**kwargs):
        saved = directory / "review-01"
        assert (saved / "input.json").is_file()
        assert len(list(saved.glob("page-*.png"))) == 13
        assert kwargs["images"] == source["images"] and kwargs["timeout"] == 30
        if provider_failed:
            raise LLMError(ErrorCode.SAFETY_OUTPUT, sentinel, raw_output=sentinel)
        return review()

    wrapped = module.wrap_review(provider, directory, root)
    if provider_failed:
        with pytest.raises(LLMError) as caught:
            await wrapped(**source, timeout=30)
        assert caught.value.code == ErrorCode.SAFETY_OUTPUT
    else:
        result = await wrapped(**source, timeout=30)
        assert result == review()
    restored = module.load_review_input(directory / "review-01", repository_root=root)
    assert restored == source
    saved_result = json.loads((directory / "review-01/review.json").read_text())
    if provider_failed:
        assert saved_result == {"status": "review_failed", "error_code": "SAFETY_OUTPUT"}
    else:
        assert saved_result == {"status": "validated_response", "review": review().model_dump(mode="json")}
    for path in (directory / "review-01").iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if path.suffix == ".json":
            assert sentinel not in path.read_text()


@pytest.mark.asyncio
async def test_first_and_second_review_remain_independent_without_extra_calls(capture):
    module, root, directory = capture
    provider = AsyncMock(return_value=review())
    wrapped = module.wrap_review(provider, directory, root)
    await wrapped(**inputs())
    await wrapped(**inputs())
    with pytest.raises(module.CaptureError, match="REVIEW_LIMIT"):
        await wrapped(**inputs())
    assert provider.await_count == 2
    assert (directory / "review-01/input.json").is_file()
    assert (directory / "review-02/input.json").is_file()


@pytest.mark.parametrize("classification,opt_in", [("real_child", "true"), ("fictional_image", "false"), ("", "true")])
def test_real_child_or_missing_opt_in_never_installs_capture(capture, monkeypatch, classification, opt_in):
    module, _root, directory = capture
    monkeypatch.setenv("LIVE_FICTIONAL_REVIEW_CAPTURE", opt_in)
    monkeypatch.setenv("LIVE_ACCEPTANCE_SOURCE_CLASSIFICATION", classification)
    with pytest.raises(module.CaptureError, match="REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN"):
        module.install()
    assert list(directory.iterdir()) == []


@pytest.mark.asyncio
async def test_provider_credential_in_generated_context_is_never_saved(capture, monkeypatch):
    module, root, directory = capture
    private_key = "inert-private-provider-key-do-not-save"
    monkeypatch.setattr(settings, "llm_api_key", private_key)
    source = inputs()
    source["page_texts"][2] += private_key
    provider = AsyncMock(return_value=review())
    with pytest.raises(module.CaptureError, match="CREDENTIAL_REJECTED"):
        await module.wrap_review(provider, directory, root)(**source)
    provider.assert_not_awaited()
    assert list(directory.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["bytes", "shared_file", "symlink", "real_child", "filename"])
async def test_replay_rejects_tampered_or_nonprivate_evidence(capture, mutation):
    module, root, directory = capture
    await module.wrap_review(AsyncMock(return_value=review()), directory, root)(**inputs())
    folder = directory / "review-01"
    target = folder / "page-00.png"
    if mutation == "bytes":
        target.write_bytes(b"changed")
    elif mutation == "shared_file":
        target.chmod(0o644)
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(folder / "page-01.png")
    else:
        record = json.loads((folder / "input.json").read_text())
        if mutation == "real_child":
            record["classification"] = "real_child"
        else:
            record["images"][0]["file"] = "../private-source.png"
        (folder / "input.json").write_text(json.dumps(record))
    with pytest.raises((module.CaptureError, OSError)):
        module.load_review_input(folder, repository_root=root)


def test_capture_directory_requires_git_ignore_owner_permissions_and_no_symlink(capture):
    module, root, directory = capture
    visible = root / "visible"
    visible.mkdir(mode=0o700)
    with pytest.raises(module.CaptureError, match="GIT_IGNORE"):
        module.wrap_review(AsyncMock(), visible, root)
    directory.chmod(0o755)
    with pytest.raises(module.CaptureError, match="PRIVATE_DIRECTORY"):
        module.wrap_review(AsyncMock(), directory, root)
    directory.chmod(0o700)
    link = root / "symlink"
    link.symlink_to(directory)
    with pytest.raises(module.CaptureError, match="PATH_INVALID"):
        module.wrap_review(AsyncMock(), link, root)


@pytest.mark.asyncio
async def test_review_only_replay_uses_exact_inputs_once_and_never_replaces_original_evidence(capture, monkeypatch):
    import httpx
    import replay_fictional_review as replay
    from src.services import image_quality

    module, root, directory = capture
    source = inputs()
    await module.wrap_review(AsyncMock(return_value=review()), directory, root)(**source)
    saved = directory / "review-01"
    original_files = {p.name: p.read_bytes() for p in saved.iterdir()}
    output = directory / "replay-output"
    output.mkdir(mode=0o700)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_model", "gpt-5.6-sol")
    monkeypatch.setattr(settings, "llm_api_key", "inert-replay-key")
    requests = []

    async def post(_self, url, **kwargs):
        requests.append(url)
        content = kwargs["json"]["input"][-1]["content"]
        assert json.loads(content[0]["text"])["title"] == source["title"]
        assert sum(item["type"] == "input_image" for item in content) == 13
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "status": "completed", "error": None, "incomplete_details": None,
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": review().model_dump_json()}]}],
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    assert await replay.review_once(saved, output, root) == 0
    assert requests == ["https://api.openai.com/v1/responses"]
    result = json.loads((output / "result.json").read_text())
    assert result["provider_calls"] == 1 and result["new_images"] == 0
    assert result["review"] == review().model_dump(mode="json")
    assert result["release_approved"] is False
    assert {p.name: p.read_bytes() for p in saved.iterdir()} == original_files

    async def mistakenly_repeated_review(**_kwargs):
        async with httpx.AsyncClient() as client:
            await client.post("https://api.openai.com/v1/responses", json={})
            await client.post("https://api.openai.com/v1/responses", json={})

    calls = []
    async def inert_post(_self, url, **_kwargs):
        calls.append(url)
        return httpx.Response(200)
    monkeypatch.setattr(httpx.AsyncClient, "post", inert_post)
    monkeypatch.setattr(image_quality, "review_book_illustrations", mistakenly_repeated_review)
    rejected = directory / "repeated-output"
    rejected.mkdir(mode=0o700)
    assert await replay.review_once(saved, rejected, root) == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_replay_parent_uses_existing_guard_without_credentials_in_argv_or_source_copy(capture, monkeypatch):
    import replay_fictional_review as replay
    import run_live_book_acceptance as runner
    import run_live_photo_acceptance as photo
    import dotenv
    from datetime import datetime, timezone

    module, root, directory = capture
    await module.wrap_review(AsyncMock(return_value=review()), directory, root)(**inputs())
    policy = directory / "policy.json"
    policy.write_text(json.dumps({
        "llm_model": "gpt-5.6-sol", "photo_analysis_model": "gpt-5.6-sol", "image_model": "gpt-image-2",
        "max_budget_usd": 1, "llm_request_reservation_usd": .4, "image_request_reservation_usd": .12,
        "provider_conditions_verified": True, "checked_at": datetime.now(timezone.utc).isoformat(),
        "evidence_note": "Inert fictional unit test evidence only.",
        "pricing_evidence": "Inert policy used by tests without real provider calls.",
    }))
    policy.chmod(0o600)
    args = SimpleNamespace(live=True, capture_dir=directory / "review-01", policy_file=policy,
                           env_file=directory / "inert.env", output_dir=directory / "output")
    private_key = "inert-parent-replay-private-key"
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *_a, **_kw: {
        "LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-5.6-sol", "LLM_API_KEY": private_key,
        "PHOTO_ANALYSIS_PROVIDER": "openai", "PHOTO_ANALYSIS_MODEL": "gpt-5.6-sol",
        "PHOTO_ANALYSIS_API_KEY": private_key, "IMAGE_PROVIDER": "openai",
        "IMAGE_MODEL": "gpt-image-2", "IMAGE_API_KEY": private_key,
    })
    monkeypatch.setattr(runner, "require_ignored_path", lambda _p: None)
    monkeypatch.setattr(photo, "require_ignored_path", lambda _p: None)
    child_calls = []

    def child(command, **kwargs):
        child_calls.append(command)
        assert private_key not in str(command)
        assert kwargs["env"]["LLM_API_KEY"] == private_key
        assert kwargs["env"]["PHOTO_PROCESSING_ENABLED"] == "true"
        assert kwargs["env"]["OPENAI_IMAGE_QUALITY"] == "medium"
        scratch = kwargs["cwd"]
        assert not list(scratch.glob(".env*"))
        assert "photo_acceptance_guard" in (scratch / "live_entry.py").read_text()
        assert kwargs["timeout"] == 75
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(replay.subprocess, "run", child)
    assert replay.run(args) == 0
    assert len(child_calls) == 1
    for file in args.output_dir.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert private_key not in file.read_text()
