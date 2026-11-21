"""Release preflight cannot confuse configured keys with live launch acceptance."""

import importlib.util
from datetime import date
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("external_preflight", ROOT / "scripts/final_external_preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def configured():
    return {
        "LLM_PROVIDER": "openai", "LLM_API_KEY": "synthetic-openai-key", "LLM_MODEL": "gpt-5.6-sol",
        "ILLUSTRATION_QUALITY_ENABLED": "true",
        "IMAGE_PROVIDER": "openai", "IMAGE_API_KEY": "synthetic-openai-image-key", "IMAGE_MODEL": "gpt-image-2",
        "S3_ENDPOINT": "https://storage.invalid", "S3_ACCESS_KEY": "synthetic-access",
        "S3_SECRET_KEY": "synthetic-storage-secret", "S3_BUCKET": "storybook",
        "S3_PUBLIC_URL": "https://storage.invalid/storybook", "ADMIN_API_KEY": "a" * 40,
        "IAP_VERIFICATION_MODE": "strict", "CORS_ORIGINS": "https://app.invalid",
        "PROD_API_URL": "https://api.invalid", "DAILY_GENERATION_BUDGET": "20",
        "PRIVACY_POLICY_URL": "https://storybook.pages.dev/privacy",
        "TERMS_OF_SERVICE_URL": "https://storybook.pages.dev/terms",
    }


def test_free_beta_does_not_require_disabled_features_or_store_credentials(configured):
    result = preflight.assess(configured)
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"
    assert result["launch_ready"] is False
    assert result["features"]["illustration_quality"] is True
    assert not any(value for name, value in result["features"].items() if name != "illustration_quality")
    assert result["required_external_evidence"]


def test_external_neon_psycopg_requires_verified_channel_binding():
    values = {
        'DATABASE_URL': 'postgresql+psycopg://user:password@db.invalid/storybook?sslmode=verify-full&channel_binding=require',
        'DATABASE_SSL_MODE': 'verify-full', 'DATABASE_SSL_ROOT_CERT': '/ca.pem',
        'S3_REGION': 'ap-southeast-1', 'S3_ADDRESSING_STYLE': 'path', 'S3_AUTO_CREATE_BUCKET': 'false',
        'S3_ENDPOINT': 'https://storage.invalid', 'S3_DOWNLOAD_ENDPOINT': 'https://storage.invalid',
    }
    errors = preflight.external_infrastructure_errors(values)
    assert not any(error.startswith('DATABASE_URL') for error in errors)
    for bad in ('channel_binding=disable', 'channel_binding=', 'channel_binding=require&channel_binding=disable'):
        values['DATABASE_URL'] = values['DATABASE_URL'].split('&channel_binding=')[0] + '&' + bad
        assert any('channel binding' in e for e in preflight.external_infrastructure_errors(values))
    values['DATABASE_URL'] = values['DATABASE_URL'].replace('postgresql+psycopg', 'postgresql+asyncpg')
    assert any('channel binding' in e for e in preflight.external_infrastructure_errors(values))


@pytest.mark.parametrize("name,value", [
    ("TESTING", "true"), ("DEBUG", "yes"), ("ENABLE_TEST_HOOKS", "1"),
    ("REQUIRE_PARENTAL_CONSENT_ENABLED", "false"),
    ("REQUIRE_PARENTAL_CONSENT_ENABLED", "unknown"),
])
def test_release_blocks_test_bypasses_and_disabled_parental_consent(configured, name, value):
    result = preflight.assess({**configured, name: value})
    assert result["status"] == "BLOCKED"
    assert any(item.startswith(name + " ") for item in result["invalid_configuration"])


def test_enabled_purchases_require_both_stores_without_relaxing_receipts(configured):
    result = preflight.assess({**configured, "PURCHASES_ENABLED": "true"})
    assert result["status"] == "BLOCKED"
    assert {"APPLE_BUNDLE_ID", "GOOGLE_PLAY_AUTH", "GOOGLE_PLAY_PACKAGE_NAME",
            "GOOGLE_RTDN_AUDIENCE", "GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL"} <= set(result["missing_or_placeholder"])
    result = preflight.assess({**configured, "IAP_VERIFICATION_MODE": "hybrid"})
    assert "IAP_VERIFICATION_MODE" in result["invalid_configuration"]


@pytest.mark.parametrize("overrides,invalid", [
    ({"LLM_PROVIDER": "anthropic", "LLM_MODEL": "gpt-wrong-family"}, "LLM_MODEL"),
    ({"ILLUSTRATION_QUALITY_ENABLED": "false"}, "ILLUSTRATION_QUALITY_ENABLED (required for release)"),
    ({"LLM_MODEL": "gpt-unverified"}, "ILLUSTRATION_QUALITY_MODEL"),
    ({"DAILY_GENERATION_BUDGET": "0"}, "DAILY_GENERATION_BUDGET"),
    ({"IMAGE_MAX_CONCURRENT": "0"}, "IMAGE_MAX_CONCURRENT (at least one image slot required)"),
    ({"OPENAI_IMAGE_QUALITY": "hd"}, "OPENAI_IMAGE_QUALITY"),
    ({"PROD_API_URL": "http://localhost:8000"}, "PROD_API_URL"),
    ({"PURCHASES_ENABLED": "definitely"}, "PURCHASES_ENABLED"),
    ({"ADMIN_API_KEY": "short"}, "ADMIN_API_KEY"),
])
def test_invalid_release_settings_block(configured, overrides, invalid):
    result = preflight.assess({**configured, **overrides})
    assert result["status"] == "BLOCKED"
    assert invalid in result["invalid_configuration"]


def test_enabled_optional_integrations_are_checked(configured):
    result = preflight.assess({**configured, "POD_ORDERING_ENABLED": "true", "POD_MODE": "local",
                              "AUDIO_FEATURE_ENABLED": "true", "TTS_PROVIDER": "google", "STT_PROVIDER": "openai"})
    assert "POD_ORDERING_ENABLED (physical fulfillment is outside this release)" in result["invalid_configuration"]
    assert {"GOOGLE_TTS_API_KEY", "STT_API_KEY"} <= set(result["missing_or_placeholder"])


@pytest.fixture
def realtime_free_beta(configured):
    return {**configured, "AUDIO_FEATURE_ENABLED": "true", "AUDIO_NARRATION_ONLY_ENABLED": "true",
            "PROD_API_URL": "https://api.storybook-beta.net",
            "TTS_PROVIDER": "openai_realtime", "OPENAI_TTS_API_KEY": "synthetic-openai-tts-key",
            "GENERATION_ACCESS_MODE": "invite_only", "GENERATION_ALLOWED_USER_HASHES": "a" * 64,
            "FREE_PLAN_FIRST_BOOK_TRIAL": "true",
            "DAILY_GENERATION_BUDGET": "14"}


def test_free_beta_accepts_narration_only_without_stt(realtime_free_beta):
    result = preflight.assess(realtime_free_beta, free_beta=True)
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"
    assert not result["launch_ready"]
    assert any("project-level ZDR" in gate for gate in result["required_external_evidence"])
    full_audio = {**realtime_free_beta, "AUDIO_NARRATION_ONLY_ENABLED": "false"}
    assert "STT_PROVIDER" in preflight.assess(full_audio, free_beta=True)["missing_or_placeholder"]


def test_free_beta_realtime_requires_dedicated_tts_key(realtime_free_beta):
    result = preflight.assess({**realtime_free_beta, "OPENAI_TTS_API_KEY": ""}, free_beta=True)
    assert result["status"] == "BLOCKED"
    assert "OPENAI_TTS_API_KEY" in result["missing_or_placeholder"]


def test_realtime_release_accepts_private_key_file_instead_of_raw_key(realtime_free_beta):
    values = {**realtime_free_beta, 'OPENAI_TTS_API_KEY': '',
              'OPENAI_TTS_API_KEY_FILE': '/run/asb-provider-keys/openai.key'}
    assert preflight.assess(values, free_beta=True)['status'] == 'CONFIGURED_NOT_VERIFIED'
    conflict = preflight.assess({**values, 'OPENAI_TTS_API_KEY': 'synthetic-hidden-key'}, free_beta=True)
    assert conflict['status'] == 'BLOCKED'
    assert 'OPENAI_TTS_API_KEY (key and file are mutually exclusive)' in conflict['invalid_configuration']
    assert 'synthetic-hidden-key' not in json.dumps(conflict)
    invalid = preflight.assess({**values, 'OPENAI_TTS_API_KEY_FILE': '../openai.key'}, free_beta=True)
    assert invalid['status'] == 'BLOCKED'
    assert any(error.startswith('OPENAI_TTS_API_KEY_FILE ') for error in invalid['invalid_configuration'])


@pytest.mark.parametrize("model", ["dall-e-3", "gpt-image-unverified", "gpt-image-2.6-flare"])
def test_free_beta_rejects_openai_image_models_without_documented_zdr_support(realtime_free_beta, model):
    result = preflight.assess({**realtime_free_beta, "IMAGE_MODEL": model}, free_beta=True)
    assert result["status"] == "BLOCKED"
    assert any(error.startswith("IMAGE_MODEL (OpenAI image model") for error in result["invalid_configuration"])


def test_free_beta_checks_the_repair_model_for_zdr_separately(realtime_free_beta, monkeypatch):
    monkeypatch.setattr(preflight, "OPENAI_ZDR_IMAGE_MODELS", preflight.OPENAI_ZDR_IMAGE_MODELS | {"gpt-image-2.6-flare"})
    result = preflight.assess({**realtime_free_beta, "IMAGE_MODEL": "gpt-image-2.6-flare",
                               "OPENAI_ILLUSTRATION_REPAIR_MODEL": "gpt-image-2.6-sunburst"}, free_beta=True)
    assert result["status"] == "BLOCKED"
    assert any(error.startswith("OPENAI_ILLUSTRATION_REPAIR_MODEL ") for error in result["invalid_configuration"])


def test_project_zdr_evidence_includes_text_and_images_with_audio_and_photos_disabled(configured):
    result = preflight.assess(configured)
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"
    assert not result["features"]["audio"] and not result["features"]["photo_processing"]
    assert any("project-level ZDR" in gate and "story, illustrations, review" in gate
               for gate in result["required_external_evidence"])


@pytest.mark.parametrize("field,provider", [
    ("TTS_PROVIDER", "google_gemini"), ("IMAGE_PROVIDER", "gemini"), ("LLM_PROVIDER", "gemini"),
])
def test_child_facing_release_blocks_google_generative_ai(realtime_free_beta, field, provider):
    result = preflight.assess({**realtime_free_beta, field: provider})
    assert result["status"] == "BLOCKED"
    assert field in result["invalid_configuration"]


@pytest.mark.parametrize("field,value", [
    ("DAILY_GENERATION_BUDGET", "13"),
    ("DAILY_JOB_LIMIT_PER_USER", "0"),
    ("MAX_PENDING_JOBS_PER_USER", "0"),
    ("MAX_PENDING_JOBS", "0"),
    ("GENERATION_ACCESS_MODE", "paused"),
    ("FREE_PLAN_FIRST_BOOK_TRIAL", "false"),
    ("PURCHASES_ENABLED", "true"),
    ("TTS_PROVIDER", "openai"),
    ("TTS_PROVIDER", "google_gemini"),
    ("AUDIO_FEATURE_ENABLED", "false"),
])
def test_free_beta_requires_complete_book_capacity_and_available_access(realtime_free_beta, field, value):
    result = preflight.assess({**realtime_free_beta, field: value}, free_beta=True)
    assert result["status"] == "BLOCKED"
    gate = "TTS_PROVIDER" if field == "AUDIO_FEATURE_ENABLED" else field
    assert any(item.startswith(gate + " (") for item in result["invalid_configuration"])


def test_public_first_book_keeps_limits_and_does_not_require_an_invitation(realtime_free_beta):
    values = {**realtime_free_beta, "GENERATION_ACCESS_MODE": "open", "GENERATION_ALLOWED_USER_HASHES": ""}
    assert preflight.assess(values, free_beta=True)["status"] == "CONFIGURED_NOT_VERIFIED"


def test_free_beta_accepts_one_slot_at_each_book_guardrail(realtime_free_beta):
    result = preflight.assess({
        **realtime_free_beta,
        "DAILY_JOB_LIMIT_PER_USER": "1",
        "MAX_PENDING_JOBS_PER_USER": "1",
        "MAX_PENDING_JOBS": "1",
    }, free_beta=True)
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"


@pytest.mark.parametrize("field,value", [
    ("PROD_API_URL", "https://8.8.8.8"),
    ("PROD_API_URL", "https://api.storybook-beta.net/health"),
    ("PRIVACY_POLICY_URL", "https://storybook.pages.dev/privacy?draft=1"),
])
def test_free_beta_checks_mobile_url_constraints(realtime_free_beta, field, value):
    result = preflight.assess({**realtime_free_beta, field: value}, free_beta=True)
    assert result["status"] == "BLOCKED"
    assert any(item.startswith(field + " ") for item in result["invalid_configuration"])


def test_json_report_never_exposes_keys_or_executes_dotenv_content(tmp_path, configured):
    marker = tmp_path / "must-not-exist"
    configured["LLM_API_KEY"] = f"$(touch {marker})"
    env_file = tmp_path / "release.env"
    env_file.write_text("\n".join(f"{key}='{value}'" for key, value in configured.items()))
    result = subprocess.run(["bash", str(ROOT / "scripts/final-external-preflight.sh"),
                             "--env-file", str(env_file), "--json"], capture_output=True, text=True,
                            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    body = json.loads(result.stdout)
    assert body["configuration_only"] is True
    assert not marker.exists()
    assert "synthetic-" not in result.stdout
    assert "$(touch" not in result.stdout


def test_placeholder_ai_key_is_blocked(configured):
    result = preflight.assess({**configured, "LLM_API_KEY": "sk-mock-placeholder"})
    assert result["status"] == "BLOCKED"
    assert "LLM_API_KEY" in result["missing_or_placeholder"]


def test_private_key_paths_are_configuration_only_and_conflicts_are_rejected(configured):
    values = {**configured, 'LLM_API_KEY': '', 'IMAGE_API_KEY': '',
              'LLM_API_KEY_FILE': '/run/asb-provider-keys/one',
              'IMAGE_API_KEY_FILE': '/run/asb-provider-keys/two'}
    result = preflight.assess(values)
    assert result['status'] == 'CONFIGURED_NOT_VERIFIED'
    assert result['launch_ready'] is False
    assert 'LLM_API_KEY' not in result['missing_or_placeholder']
    conflict = preflight.assess({**values, 'LLM_API_KEY': 'sensitive-value'})
    assert conflict['status'] == 'BLOCKED'
    assert any(item.startswith('LLM_API_KEY ') for item in conflict['invalid_configuration'])
    assert 'sensitive-value' not in json.dumps(conflict)
    invalid = preflight.assess({**values, 'IMAGE_API_KEY_FILE': '../relative'})
    assert any(item.startswith('IMAGE_API_KEY_FILE ') for item in invalid['invalid_configuration'])


@pytest.mark.parametrize("name", ["PRIVACY_POLICY_URL", "TERMS_OF_SERVICE_URL"])
@pytest.mark.parametrize("value", [None, "", "https://your-site.pages.dev/policy"])
def test_public_policy_urls_are_required_even_when_paid_features_are_disabled(configured, name, value):
    values = {**configured, name: value}
    result = preflight.assess(values)
    assert result["status"] == "BLOCKED"
    assert name in result["missing_or_placeholder"]
    assert result["launch_ready"] is False


@pytest.mark.parametrize("name", ["PRIVACY_POLICY_URL", "TERMS_OF_SERVICE_URL"])
@pytest.mark.parametrize("value", [
    "http://storybook.pages.dev/privacy",
    "file:///privacy.html",
    "https://localhost/privacy",
    "https://127.0.0.1/privacy",
    "https://127.1/privacy",
    "https://192.168.1.2/privacy",
    "https://[::1]/privacy",
    "https://policies.internal/privacy",
    "https://account:password@storybook.pages.dev/privacy",
    "https://@storybook.pages.dev/privacy",
    "https://storybook.pages.dev:99999/privacy",
])
def test_nonpublic_or_non_https_policy_urls_block_release_configuration(configured, name, value):
    result = preflight.assess({**configured, name: value})
    assert result["status"] == "BLOCKED"
    assert name in result["invalid_configuration"]
    assert value not in json.dumps(result)


@pytest.mark.parametrize("origin", [
    "https://storybook.pages.dev",
    "https://storybook.vercel.app",
    "https://storybook.netlify.app",
    "https://sites.google.com/view/storybook",
])
def test_hosting_provider_policy_addresses_do_not_require_a_custom_domain(configured, origin):
    result = preflight.assess({
        **configured,
        "PRIVACY_POLICY_URL": f"{origin}/privacy",
        "TERMS_OF_SERVICE_URL": f"{origin}/terms",
    })
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"
    assert result["launch_ready"] is False
    assert result["configuration_only"] is True
    evidence = " ".join(result["required_external_evidence"]).lower()
    assert "privacy policy" in evidence
    assert "terms of service" in evidence
    assert "support pages open without login" in evidence


def test_public_policy_build_defines_are_documented_without_backend_forwarding():
    schema = json.loads((ROOT / "env.schema.json").read_text())
    api_settings = (ROOT / "apps/api/src/core/config.py").read_text()
    compose_files = [ROOT / "infra/docker-compose.yml", ROOT / "infra/docker-compose.prod.yml"]
    for name in ("PRIVACY_POLICY_URL", "TERMS_OF_SERVICE_URL"):
        description = schema["properties"][name]["description"]
        assert f"--dart-define={name}" in description
        assert "Operator/mobile-build setting only" in description
        assert name not in schema["required"]
        assert name not in api_settings
        assert all(name not in path.read_text() for path in compose_files)


@pytest.mark.parametrize("key", ["minioadmin", "minioadmin123", "miniostorybook", "test-access-key", "test-secret-key"])
def test_development_storage_credentials_are_blocked(configured, key):
    result = preflight.assess({**configured, "S3_ACCESS_KEY": key, "S3_SECRET_KEY": key})
    assert result["status"] == "BLOCKED"
    assert {"S3_ACCESS_KEY", "S3_SECRET_KEY"} <= set(result["missing_or_placeholder"])


@pytest.mark.parametrize("enabled", ["true", "True", "1", "yes", "on"])
def test_compose_preflight_cannot_skip_store_requirements_using_boolean_aliases(tmp_path, configured, enabled):
    values = {**configured, "DB_USER": "storybook", "DB_PASSWORD": "synthetic-db-secret",
              "DB_NAME": "storybook", "PURCHASES_ENABLED": enabled}
    env_file = tmp_path / "production.env"
    env_file.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()))
    result = subprocess.run(["bash", str(ROOT / "scripts/check-env.sh"), "--mode", "production",
                             "--env-file", str(env_file)], capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 1
    assert "APPLE_BUNDLE_ID is required" in result.stdout
    assert "GOOGLE_RTDN_AUDIENCE is required" in result.stdout


def test_compose_preflight_accepts_free_beta_without_store_credentials(tmp_path, configured):
    values = {**configured, "DB_USER": "storybook", "DB_PASSWORD": "synthetic-db-secret",
              "DB_NAME": "storybook", "PURCHASES_ENABLED": "false"}
    env_file = tmp_path / "production.env"
    env_file.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()))
    result = subprocess.run(["bash", str(ROOT / "scripts/check-env.sh"), "--mode", "production",
                             "--env-file", str(env_file)], capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("quality", ["low", "medium", "high", "auto"])
def test_explicit_openai_image_quality_is_valid_configuration(configured, quality):
    result = preflight.assess({**configured, "OPENAI_IMAGE_QUALITY": quality})
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"


@pytest.mark.parametrize("change", [
    {"publication_status": "review"}, {"effective_date": None},
    {"effective_date": "2026-99-99"}, {"operator": ""},
    {"contact_email": ""}, {"sections": []}, {"title": " "},
    {"sections": [{"heading": "Fixture", "paragraphs": [" "]}]},
    {"sections": [{"heading": "Fixture", "paragraphs": "Not an array"}]},
    {"version_label": "v1"},
    {"version_label": "시행일 2026-09-06"},
    {"version_label": "버전 2026-09-07 · 시행일 2026-09-06"},
    {"version_label": "2026-09-07 검토본 · 시행일은 공개 시 확정"},
    {"introduction": "현재 공개 전 검토본입니다."},
    {"sections": [{"heading": "외부 처리와 국외 이전", "paragraphs": [
        "공개 전 확정 항목은 실제 처리 업체와 문의처입니다."]}]},
    {"sections": [{"heading": "보관과 삭제", "paragraphs": [
        "공개본에 보존 대상·근거·기간과 백업 만료 기준을 명시합니다."]}]},
    {"effective_date": "2026-09-08", "version_label": "시행일 2026-09-08"},
])
def test_bundled_policy_release_gate_requires_both_complete_documents(tmp_path, change):
    assets = tmp_path / "apps/mobile/assets/legal"
    assets.mkdir(parents=True)
    approved = {"publication_status": "approved", "effective_date": "2026-09-07",
                "operator": "Fictional operator", "contact_email": "support@storybook-fixture.org",
                "title": "Test policy", "version_label": "시행일 2026-09-07", "introduction": "Test introduction",
                "sections": [{"heading": "Fixture", "paragraphs": ["Fixture document."]}]}
    (assets / "privacy.ko.json").write_text(json.dumps(approved))
    (assets / "terms.ko.json").write_text(json.dumps(approved))
    today = date(2026, 9, 7)
    assert preflight.assess_bundled_policies(tmp_path, today=today)["ready"] is True
    (assets / "terms.ko.json").write_text(json.dumps({**approved, **change}))
    report = preflight.assess_bundled_policies(tmp_path, today=today)
    assert report["ready"] is False
    assert report["documents"]["privacy"] == "approved"
    assert report["documents"]["terms"] != "approved"
    if change.get("effective_date") == "2026-09-08":
        assert report["documents"]["terms"] == "not_effective"
        assert preflight.assess_bundled_policies(tmp_path, today=date(2026, 9, 8))["ready"]


def test_missing_policy_asset_fails_release_gate(tmp_path):
    assert preflight.assess_bundled_policies(tmp_path)["ready"] is False


def test_openai_narration_configuration_requires_dedicated_key(configured):
    result = preflight.assess({**configured, 'AUDIO_FEATURE_ENABLED': 'true',
                              'TTS_PROVIDER': 'openai', 'STT_PROVIDER': 'openai'})
    assert 'OPENAI_TTS_API_KEY' in result['missing_or_placeholder']


def test_planned_feature_check_does_not_rewrite_env(tmp_path):
    env_file = tmp_path / 'release.env'
    original = 'PURCHASES_ENABLED=false\nAUDIO_FEATURE_ENABLED=false\nPOD_ORDERING_ENABLED=false\n'
    env_file.write_text(original)
    result = subprocess.run(['bash', str(ROOT / 'scripts/final-external-preflight.sh'),
                             '--env-file', str(env_file), '--check-planned-features', '--json'],
                            capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload['planned_features_only'] is True
    assert payload['features']['new_purchases'] is True
    assert payload['features']['audio'] is True
    assert payload['features']['physical_orders'] is False
    assert 'PRINTFUL_API_KEY' not in payload['missing_or_placeholder']
    assert 'APPLE_BUNDLE_ID' in payload['missing_or_placeholder']
    assert env_file.read_text() == original


def test_native_store_notifications_require_verified_audience_and_app_identity(configured):
    result = preflight.assess({**configured, "PURCHASES_ENABLED": "true", "APPLE_APP_ID": "0",
                              "APPLE_NOTIFICATION_ENVIRONMENT": "Sandbox", "GOOGLE_RTDN_AUDIENCE": "http://localhost",
                              "GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL": "ordinary@gmail.com"})
    assert "APPLE_APP_ID (positive App Store ID required)" in result["invalid_configuration"]
    assert "APPLE_NOTIFICATION_ENVIRONMENT (Production required for release)" in result["invalid_configuration"]
    assert "GOOGLE_RTDN_AUDIENCE (public HTTPS push audience required)" in result["invalid_configuration"]
    assert "GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL" in result["invalid_configuration"]


def test_native_store_configuration_does_not_require_legacy_adapter_secrets(configured):
    result = preflight.assess({**configured, 'PURCHASES_ENABLED': 'true', 'APPLE_BUNDLE_ID': 'com.storybook.app',
        'APPLE_APP_ID': '1234567890', 'GOOGLE_PLAY_PACKAGE_NAME': 'com.storybook.app',
        'GOOGLE_PLAY_SERVICE_ACCOUNT_JSON': 'synthetic-credential-present',
        'GOOGLE_RTDN_AUDIENCE': 'https://storybook.onrender.com/v1/iap/notifications/google',
        'GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL': 'push@storybook.iam.gserviceaccount.com'})
    assert result['status'] == 'CONFIGURED_NOT_VERIFIED'
    assert result['launch_ready'] is False
    assert 'APPLE_IAP_SHARED_SECRET' not in result['missing_or_placeholder']
    assert 'IAP_WEBHOOK_SECRET' not in result['missing_or_placeholder']


def test_physical_fulfillment_cannot_be_mistaken_for_current_release_scope(configured):
    result = preflight.assess({**configured, 'POD_ORDERING_ENABLED': 'true', 'POD_MODE': 'strict',
        'POD_PROVIDER': 'printful', 'PRINTFUL_API_KEY': 'synthetic-print-credential', 'PRINTFUL_SYNC_VARIANT_ID': '1234'})
    assert result['status'] == 'BLOCKED'
    assert 'POD_ORDERING_ENABLED (physical fulfillment is outside this release)' in result['invalid_configuration']
