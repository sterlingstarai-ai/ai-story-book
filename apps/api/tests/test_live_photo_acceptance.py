"""Private photo acceptance preparation and API journey; no paid HTTP or child data."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest


@pytest.fixture
def script(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import run_live_photo_acceptance
    monkeypatch.setattr(run_live_photo_acceptance, "require_ignored_path", lambda _path: None)
    return run_live_photo_acceptance


def policy():
    return {
        "llm_model": "gpt-5.6-sol", "photo_analysis_model": "gpt-5.6-sol", "image_model": "gpt-image-2",
        "max_budget_usd": 4, "llm_request_reservation_usd": 0.1, "image_request_reservation_usd": 0.15,
        "provider_conditions_verified": True, "checked_at": datetime.now(timezone.utc).isoformat(),
        "evidence_note": "Operator verified selected fictional-input API project conditions.",
        "pricing_evidence": "Operator verified official standard prices; estimates are not invoice caps.",
    }


def manifest(tmp_path):
    return {"classification": "fictional_image", "source_path": str(tmp_path / "source.png"),
            "character_name": "가상 인물", "age_band": "7-9", "contains_real_person": False,
            "source_provenance": "Entirely invented local test image; not based on a person."}


def png():
    data = BytesIO()
    Image.new("RGB", (32, 32), "blue").save(data, format="PNG")
    return data.getvalue()


def test_fictional_input_does_not_require_real_child_zdr_but_never_claims_likeness(script, tmp_path):
    assert script.validate_manifest(manifest(tmp_path))["classification"] == "fictional_image"
    assert script.verified_policy(policy(), "fictional_image")["image_model"] == "gpt-image-2"
    with pytest.raises(script.GateFailure, match="REAL_CHILD_PROVIDER"):
        script.verified_policy(policy(), "real_child")
    configured = {**policy(), "zdr_applied_to_all_selected_projects": True,
                  "under18_processing_conditions_verified": True}
    script.verified_policy(configured, "real_child")


@pytest.mark.parametrize("change", [
    {"classification": "unknown"}, {"contains_real_person": True}, {"source_provenance": ""},
    {"classification": "real_child", "parent_authorized": False},
])
def test_missing_provenance_or_authorization_is_rejected(script, tmp_path, change):
    with pytest.raises(script.GateFailure):
        script.validate_manifest({**manifest(tmp_path), **change})


def test_private_source_rejects_shared_files_and_symlinks(script, tmp_path):
    path = tmp_path / "private.png"
    path.write_bytes(png())
    path.chmod(0o644)
    with pytest.raises(script.GateFailure, match="0600"):
        script.private_bytes(path, 1024)
    path.chmod(0o600)
    link = tmp_path / "link.png"
    link.symlink_to(path)
    with pytest.raises(script.GateFailure):
        script.private_bytes(link, 1024)
    assert script.private_bytes(path, 1024) == png()


def test_approval_is_bound_to_reviewed_version_and_portrait(script, tmp_path):
    portrait = tmp_path / "portrait.png"
    portrait.write_bytes(png())
    portrait.chmod(0o600)
    digest = hashlib.sha256(png()).hexdigest()
    script.save_json(tmp_path / "approval-request.json", {"avatar_version": 2, "portrait_sha256": digest})
    script.approve(tmp_path, "delegated_tester")
    record = script.private_json(tmp_path / "portrait-approval.json")
    assert script.approval_matches(record, 2, digest)
    assert not script.approval_matches(record, 3, digest)
    assert not script.approval_matches(record, 2, "changed")


def test_authentication_failure_is_not_misreported_as_visual_quality_failure(script, tmp_path):
    (tmp_path / "provider-usage.jsonl").write_text(json.dumps({
        "kind": "response", "role": "image", "http_status": 401,
    }) + "\n")
    report = {}
    with pytest.raises(script.GateFailure, match="PORTRAIT_GENERATION_FAILED"):
        script.require_portrait_preview({"avatar_status": "failed"}, tmp_path, report)
    assert report["provider_failure"] == {"role": "image", "http_status": 401}
    assert "portrait_product_qa" not in report


def test_explicit_runtime_keys_do_not_fall_back_to_another_provider(script):
    values = {"LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-5.6-sol", "LLM_API_KEY": "writing-key",
              "PHOTO_ANALYSIS_PROVIDER": "openai", "PHOTO_ANALYSIS_MODEL": "gpt-5.6-sol",
              "PHOTO_ANALYSIS_API_KEY": "photo-key", "IMAGE_PROVIDER": "openai",
              "IMAGE_MODEL": "gpt-image-2", "IMAGE_API_KEY": "image-key"}
    config = script.runtime_config(values, policy())
    assert config.photo_analysis_api_key == "photo-key"
    with pytest.raises(script.GateFailure, match="EXPLICIT_PHOTO_PROVIDER_KEY"):
        script.runtime_config({**values, "PHOTO_ANALYSIS_API_KEY": None}, policy())
    assert values["PHOTO_ANALYSIS_API_KEY"] == "photo-key"


@pytest.mark.parametrize("retain_evidence", [False, True])
def test_live_profile_matches_product_fan_out_without_relaxing_deadlines_or_request_guard(
    script, monkeypatch, tmp_path, retain_evidence,
):
    from src.core.config import Settings

    data = manifest(tmp_path)
    source = Path(data["source_path"])
    source.write_bytes(png())
    source.chmod(0o600)
    args = SimpleNamespace(live=True, input_manifest=tmp_path / "manifest.json",
                           policy_file=tmp_path / "policy.json", env_file=tmp_path / "inert.env",
                           output_dir=tmp_path / "output", review_timeout_seconds=600,
                           retain_fictional_review_evidence=retain_evidence)
    script.save_json(args.input_manifest, data)
    script.save_json(args.policy_file, policy())
    args.env_file.touch()
    monkeypatch.setattr(script, "dotenv_values", lambda *_a, **_kw: {
        "LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-5.6-sol", "LLM_API_KEY": "inert-writing-key",
        "PHOTO_ANALYSIS_PROVIDER": "openai", "PHOTO_ANALYSIS_MODEL": "gpt-5.6-sol",
        "PHOTO_ANALYSIS_API_KEY": "inert-photo-key", "IMAGE_PROVIDER": "openai",
        "IMAGE_MODEL": "gpt-image-2", "IMAGE_API_KEY": "inert-image-key",
    })
    captured = {}

    def capture(options, *, profile):
        captured.update(options=options, profile=profile)
        return 0

    monkeypatch.setattr(script, "run_acceptance", capture)
    assert script.run(args) == 0
    profile = captured["profile"]
    assert int(profile.environment["IMAGE_MAX_CONCURRENT"]) == Settings.model_fields["image_max_concurrent"].default == 3
    assert profile.report_fields["image_max_concurrent"] == int(profile.environment["IMAGE_MAX_CONCURRENT"])
    assert profile.environment["ILLUSTRATION_QUALITY_ENABLED"] == "true"
    assert profile.environment["OPENAI_IMAGE_QUALITY"] == "medium"
    assert not any("TIMEOUT" in name or "SLA" in name or "DEADLINE" in name for name in profile.environment)
    assert profile.guard_module == "photo_acceptance_guard"
    assert profile.request_limits == {"llm": 16, "image": 17}
    assert profile.environment["LIVE_PHOTO_POLICY_FILE"] == str(args.policy_file.resolve())
    assert captured["options"].page_count == 12
    assert profile.retain_fictional_review_evidence is retain_evidence
    assert profile.report_fields["fictional_review_evidence_retained"] is retain_evidence


def test_real_child_capture_is_rejected_before_configuration_source_read_or_provider(script, tmp_path, monkeypatch):
    data = {**manifest(tmp_path), "classification": "real_child", "parent_authorized": True}
    args = SimpleNamespace(live=True, input_manifest=tmp_path / "manifest.json", retain_fictional_review_evidence=True)
    script.save_json(args.input_manifest, data)
    monkeypatch.setattr(script, "run_acceptance", lambda *_a, **_kw: pytest.fail("Must not launch"))
    with pytest.raises(script.GateFailure, match="REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN"):
        script.run(args)


def test_failed_guard_installation_stops_before_app_import(script, tmp_path):
    from run_live_book_acceptance import write_guarded_entry

    (tmp_path / "photo_acceptance_guard.py").write_text("def install():\n    raise RuntimeError('blocked')\n")
    marker = tmp_path / "app-started"
    (tmp_path / "inert_application.py").write_text("from pathlib import Path\nPath('app-started').touch()\n")
    entry = write_guarded_entry(tmp_path, "photo_acceptance_guard")
    completed = subprocess.run([sys.executable, str(entry), "inert_application"], cwd=tmp_path,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    assert completed.returncode != 0 and not marker.exists()


def test_capture_installation_is_required_after_guard_and_before_application(script, tmp_path):
    from run_live_book_acceptance import write_guarded_entry

    (tmp_path / "photo_acceptance_guard.py").write_text("def install():\n    open('guard', 'w').close()\n")
    (tmp_path / "fictional_review_capture.py").write_text(
        "def install():\n    assert __import__('os').path.exists('guard')\n    raise RuntimeError('blocked')\n")
    (tmp_path / "inert_application.py").write_text("open('app-started', 'w').close()\n")
    entry = write_guarded_entry(tmp_path, "photo_acceptance_guard", capture_fictional_review=True)
    completed = subprocess.run([sys.executable, str(entry), "inert_application"], cwd=tmp_path,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    assert completed.returncode != 0 and (tmp_path / "guard").exists()
    assert not (tmp_path / "app-started").exists()


@pytest.mark.parametrize("approved", [True, False])
def test_journey_uses_preview_approval_before_twelve_page_book_and_cleans_sources(
    script, monkeypatch, tmp_path, approved,
):
    source = png()
    digest = hashlib.sha256(source).hexdigest()
    if approved:
        script.save_json(tmp_path / "portrait-approval.json", {
            "avatar_version": 2, "portrait_sha256": digest, "reviewed_source_and_portrait": True,
            "reviewer": "delegated_tester", "decision": "approve",
        })
    state = {"approved": False, "revoked": False, "book_started": False}
    calls = []
    def handler(request):
        assert request.url.host == "127.0.0.1"
        path, method = request.url.path, request.method
        calls.append((method, path))
        if path == "/asset.png":
            return httpx.Response(200, content=source)
        if path.endswith("/avatar/approve"):
            assert json.loads(request.content) == {"version": 2}
            state["approved"] = True
            return httpx.Response(200, json={"avatar_status": "approved"})
        if path == "/v1/characters/from-photo" or path == "/v1/characters/character":
            if method == "POST":
                assert b'filename="source.png"' in request.content
                assert b"Content-Type: image/png" in request.content
            return httpx.Response(200, json={"character_id": "character", "avatar_status": "preview",
                                            "avatar_version": 2, "avatar_url": "http://127.0.0.1/asset.png"})
        if path == "/v1/books":
            if not state["approved"]:
                return httpx.Response(409, json={})
            assert json.loads(request.content)["page_count"] == 12
            state["book_started"] = True
            return httpx.Response(200, json={"job_id": "job"})
        if path == "/v1/books/job":
            return httpx.Response(200, json={"status": "done", "result": {"book_id": "book"}})
        if path == "/v1/books/book/detail":
            return httpx.Response(200, json={"title": "가상 동화", "cover_image_url": "http://127.0.0.1/asset.png",
                                            "pages": [{"text": "가상 인물이 걸어요.", "image_url": "http://127.0.0.1/asset.png"}] * 12})
        if path == "/v1/consent/revoke":
            state["revoked"] = True
        return httpx.Response(200, json={})
    original_client = httpx.Client
    monkeypatch.setattr(script.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    def objects(**kw):
        if state["revoked"]:
            return {}
        prefix = kw["Prefix"]
        if prefix.startswith("jobs/"):
            return {"Contents": [{"Key": "jobs/job/character-reference/fixed.png"}]}
        return {"Contents": [] if state["approved"] else [{"Key": "characters/character/photo.jpg"}]}
    store = SimpleNamespace(list_objects_v2=objects, get_object=lambda **_kw: {"Body": BytesIO(source)})
    monkeypatch.setattr(script.boto3, "client", lambda *_a, **_kw: store)
    monkeypatch.setattr(script.time, "sleep", lambda _delay: None)
    runtime = {"S3_ENDPOINT": "http://127.0.0.1", "S3_ACCESS_KEY": "inert", "S3_SECRET_KEY": "inert", "S3_BUCKET": "inert"}
    report = {}
    execute = script.journey(manifest(tmp_path), source, 1 if approved else 0)
    if not approved:
        with pytest.raises(script.GateFailure, match="PORTRAIT_REVIEW_TIMEOUT"):
            execute("http://127.0.0.1", tmp_path, report, runtime)
        assert not state["approved"] and not state["book_started"]
        return
    execute("http://127.0.0.1", tmp_path, report, runtime)
    assert report["page_count"] == 12 and report["fixed_portrait_reuse"] == "passed"
    assert report["consent_withdrawal_cleanup"] == "passed" and state["revoked"]
    assert len(list(tmp_path.glob("page-*.png"))) == 13
    assert script.private_json(tmp_path / "quality-review.json")["real_child_likeness"] == "not_applicable"
    assert "http://" not in (tmp_path / "book.json").read_text()
    assert report["visual_quality_status"] == "pending" and report["launch_ready"] is False
