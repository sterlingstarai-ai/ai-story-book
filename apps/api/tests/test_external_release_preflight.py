"""Release preflight cannot confuse configured keys with live launch acceptance."""

import importlib.util
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
        "IMAGE_PROVIDER": "gemini", "IMAGE_API_KEY": "synthetic-gemini-key", "IMAGE_MODEL": "gemini-selected-image",
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


def test_enabled_purchases_require_both_stores_without_relaxing_receipts(configured):
    result = preflight.assess({**configured, "PURCHASES_ENABLED": "true"})
    assert result["status"] == "BLOCKED"
    assert {"APPLE_IAP_SHARED_SECRET", "APPLE_BUNDLE_ID", "GOOGLE_PLAY_AUTH",
            "GOOGLE_PLAY_PACKAGE_NAME", "IAP_WEBHOOK_SECRET"} <= set(result["missing_or_placeholder"])
    result = preflight.assess({**configured, "IAP_VERIFICATION_MODE": "hybrid"})
    assert "IAP_VERIFICATION_MODE" in result["invalid_configuration"]


@pytest.mark.parametrize("overrides,invalid", [
    ({"LLM_PROVIDER": "anthropic", "LLM_MODEL": "gpt-wrong-family"}, "LLM_MODEL"),
    ({"ILLUSTRATION_QUALITY_ENABLED": "false"}, "ILLUSTRATION_QUALITY_ENABLED (required for release)"),
    ({"LLM_MODEL": "gpt-unverified"}, "ILLUSTRATION_QUALITY_MODEL"),
    ({"DAILY_GENERATION_BUDGET": "0"}, "DAILY_GENERATION_BUDGET"),
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
    assert "POD_MODE" in result["invalid_configuration"]
    assert {"PRINTFUL_API_KEY", "GOOGLE_TTS_API_KEY", "STT_API_KEY"} <= set(result["missing_or_placeholder"])


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
    assert "APPLE_IAP_SHARED_SECRET is required" in result.stdout
    assert "IAP_WEBHOOK_SECRET is required" in result.stdout


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
    {"contact_email": ""}, {"sections": []},
])
def test_bundled_policy_release_gate_requires_both_complete_documents(tmp_path, change):
    assets = tmp_path / "apps/mobile/assets/legal"
    assets.mkdir(parents=True)
    approved = {"publication_status": "approved", "effective_date": "2026-09-07",
                "operator": "Fictional operator", "contact_email": "support@storybook-fixture.org",
                "sections": [{"heading": "Fixture", "paragraphs": ["Fixture document."]}]}
    (assets / "privacy.ko.json").write_text(json.dumps(approved))
    (assets / "terms.ko.json").write_text(json.dumps(approved))
    assert preflight.assess_bundled_policies(tmp_path)["ready"] is True
    (assets / "terms.ko.json").write_text(json.dumps({**approved, **change}))
    report = preflight.assess_bundled_policies(tmp_path)
    assert report["ready"] is False
    assert report["documents"]["privacy"] == "approved"
    assert report["documents"]["terms"] != "approved"


def test_missing_policy_asset_fails_release_gate(tmp_path):
    assert preflight.assess_bundled_policies(tmp_path)["ready"] is False
