"""Configuration-only launch gate with secret-free, machine-readable results."""

import argparse
from datetime import date
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.parse import parse_qs


def present(value):
    value = (value or "").strip()
    lowered = value.lower()
    if lowered in {"minioadmin", "minioadmin123", "miniostorybook", "storybook123",
                   "test-access-key", "test-secret-key"}:
        return False
    return bool(value) and not any(marker in lowered for marker in (
        "your-", "your_", "change_me", "changeme", "placeholder", "mock", "test-key",
        "example", "dummy", "replace_me", "fake-"))


def public_https_endpoint(value):
    """Reject nonpublic URL shapes without DNS, HTTP or ownership verification."""
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").rstrip(".").lower()
        # Accessing port also rejects malformed or out-of-range port values.
        parsed.port
        if (parsed.scheme != "https" or not host
                or parsed.username is not None or parsed.password is not None
                or any(character.isspace() for character in value.strip())):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            pass
        if host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
            return False
        hostname = host.encode("idna").decode("ascii")
        return ("." in hostname and len(hostname) <= 253
                and not hostname.rsplit(".", 1)[-1].isdigit()
                and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                        for label in hostname.split(".")))
    except (ValueError, UnicodeError):
        return False


def mobile_url_error(name, value):
    if not isinstance(value, str) or 'replace-me' in value or not present(value) or not public_https_endpoint(value):
        return f'{name} requires a non-placeholder public HTTPS URL.'
    parsed = urlsplit(value)
    host = (parsed.hostname or '').rstrip('.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return f'{name} requires a DNS hostname for the mobile release.'
    reserved = ('example.com', 'example.net', 'example.org')
    if (host.endswith(('.invalid', '.test', '.example'))
            or any(host == domain or host.endswith('.' + domain) for domain in reserved)):
        return f'{name} cannot use a documentation or test hostname.'
    if value != value.strip() or '?' in value or '#' in value:
        return f'{name} cannot contain surrounding whitespace, a query, or a fragment.'
    if name == 'PROD_API_URL' and parsed.path not in {'', '/'}:
        return 'PROD_API_URL must be an origin without a path.'
    return None


def external_infrastructure_errors(values):
    """Validate shapes only; never connect or expose a credential-bearing URL."""
    invalid = []
    for name in ("DATABASE_URL", "DATABASE_MIGRATION_URL"):
        raw = values.get(name, "")
        if not raw and name == "DATABASE_MIGRATION_URL":
            continue
        try:
            url = urlsplit(raw)
            query = parse_qs(url.query, keep_blank_values=True)
            if (not present(raw) or url.scheme not in {"postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
                    or not url.hostname or not url.username or not url.password
                    or not url.path.strip("/") or url.port not in {None, 5432}
                    or query.get("sslmode", ["verify-full"]) != ["verify-full"]):
                invalid.append(name + " (direct/session PostgreSQL endpoint required)")
            binding = query.get("channel_binding")
            if ((url.scheme == "postgresql+psycopg" and binding != ["require"])
                    or (url.scheme != "postgresql+psycopg" and binding is not None)):
                invalid.append(name + " (channel binding requires psycopg and require)")
            configured_ca = values.get("DATABASE_SSL_ROOT_CERT", "")
            if query.get("sslrootcert", [configured_ca]) != [configured_ca]:
                invalid.append(name + " (conflicting CA settings)")
        except ValueError:
            invalid.append(name)
    if values.get("DATABASE_SSL_MODE") != "verify-full":
        invalid.append("DATABASE_SSL_MODE (external deployment requires verify-full)")
    if not present(values.get("DATABASE_SSL_ROOT_CERT")):
        invalid.append("DATABASE_SSL_ROOT_CERT (provider CA must be mounted)")
    if not present(values.get("S3_REGION")):
        invalid.append("S3_REGION")
    if values.get("S3_ADDRESSING_STYLE", "path") != "path":
        invalid.append("S3_ADDRESSING_STYLE (external S3 deployment uses path)")
    if values.get("S3_AUTO_CREATE_BUCKET", "true").lower() not in {"false", "0", "no", "off"}:
        invalid.append("S3_AUTO_CREATE_BUCKET (pre-create a private bucket)")
    if not public_https_endpoint(values.get("S3_ENDPOINT", "")):
        invalid.append("S3_ENDPOINT (external storage requires HTTPS)")
    for name in ("API_IMAGE", "WORKER_IMAGE"):
        if not re.fullmatch(r"[^\s]+(?::[a-f0-9]{40}|@sha256:[a-f0-9]{64})", values.get(name, "")):
            invalid.append(name + " (immutable SHA image required)")
    return invalid


def assess(values, *, free_beta=False):
    """Presence is not proof of authorization, billing, legal approval or live behavior."""
    missing = []
    invalid = []
    # Internal-Postgres Compose uses DB_USER/DB_PASSWORD/DB_NAME. Supplying a
    # runtime DATABASE_URL selects the separately documented external topology.
    if values.get("DATABASE_URL"):
        invalid.extend(external_infrastructure_errors(values))
    if values.get("S3_ADDRESSING_STYLE", "path") not in {"path", "virtual", "auto"}:
        invalid.append("S3_ADDRESSING_STYLE")
    access_mode = values.get("GENERATION_ACCESS_MODE", "open")
    if access_mode not in {"open", "invite_only", "paused"}:
        invalid.append("GENERATION_ACCESS_MODE")
    if access_mode == "invite_only":
        hashes = [item.strip() for item in values.get("GENERATION_ALLOWED_USER_HASHES", "").split(",") if item.strip()]
        if not hashes or any(not re.fullmatch(r"[a-f0-9]{64}", item) for item in hashes):
            invalid.append("GENERATION_ALLOWED_USER_HASHES (valid invited account hashes required)")

    def need(name):
        if not present(values.get(name)):
            missing.append(name)

    def choice(name, accepted):
        need(name)
        if present(values.get(name)) and values[name].strip().lower() not in accepted:
            invalid.append(name)

    def enabled(name):
        value = values.get(name, "false").strip().lower()
        if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            invalid.append(name)
        return value in {"true", "1", "yes", "on"}

    # Testing can bypass parental consent, rate limits and receipt checks.
    # Hooks separately relax receipt validation, even when TESTING is false.
    for name in ("DEBUG", "TESTING", "ENABLE_TEST_HOOKS"):
        if enabled(name):
            invalid.append(name + " (must be disabled for release)")
    consent = values.get("REQUIRE_PARENTAL_CONSENT_ENABLED", "true").strip().lower()
    if consent not in {"true", "1", "yes", "on"}:
        invalid.append("REQUIRE_PARENTAL_CONSENT_ENABLED (required for release)")

    for name in ("LLM_MODEL", "IMAGE_MODEL", "S3_ENDPOINT",
                 "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET", "S3_PUBLIC_URL",
                 "ADMIN_API_KEY", "CORS_ORIGINS", "PROD_API_URL",
                 "PRIVACY_POLICY_URL", "TERMS_OF_SERVICE_URL"):
        need(name)
    for name in ("LLM_API_KEY", "IMAGE_API_KEY"):
        file_name = name + "_FILE"
        path = values.get(file_name, "")
        raw = values.get(name, "")
        if raw and path:
            invalid.append(name + " (key and file are mutually exclusive)")
        elif path:
            if (not path.startswith("/") or path.startswith("//")
                    or os.path.normpath(path) != path or path == "/"):
                invalid.append(file_name + " (absolute normalized container path required)")
        else:
            need(name)
    choice("LLM_PROVIDER", {"openai", "anthropic", "gemini"})
    choice("IMAGE_PROVIDER", {"openai", "gemini", "replicate", "fal"})
    choice("IAP_VERIFICATION_MODE", {"strict"})
    if values.get("OPENAI_IMAGE_QUALITY", "medium") not in {"low", "medium", "high", "auto"}:
        invalid.append("OPENAI_IMAGE_QUALITY")
    for provider, model in (("LLM_PROVIDER", "LLM_MODEL"), ("IMAGE_PROVIDER", "IMAGE_MODEL")):
        prefix = {"anthropic": "claude-", "gemini": "gemini-"}.get(values.get(provider))
        if prefix and present(values.get(model)) and not values[model].startswith(prefix):
            invalid.append(model)
    for name in ("IAP_WEBHOOK_SECRET", "ADMIN_API_KEY"):
        if present(values.get(name)) and len(values[name]) < 32:
            invalid.append(name)
    for name in ("PROD_API_URL", "PRIVACY_POLICY_URL", "TERMS_OF_SERVICE_URL"):
        if not present(values.get(name)):
            continue
        if free_beta:
            error = mobile_url_error(name, values[name])
            if error:
                invalid.append(error)
        elif not public_https_endpoint(values[name]):
            invalid.append(name)
    download = values.get("S3_DOWNLOAD_ENDPOINT") or values.get("S3_ENDPOINT", "")
    if present(download) and not public_https_endpoint(download):
        invalid.append("S3_DOWNLOAD_ENDPOINT (device-reachable HTTPS S3 API endpoint required)")
    def count_limit(name, minimum, reason="", *, default=0):
        try:
            value = int(values.get(name, str(default)))
        except ValueError:
            invalid.append(name)
        else:
            if value < minimum:
                invalid.append(name + reason)

    audio = enabled("AUDIO_FEATURE_ENABLED")
    narration_only = enabled("AUDIO_NARRATION_ONLY_ENABLED")
    tts_provider = values.get("TTS_PROVIDER", "").strip().lower()
    pod = enabled("POD_ORDERING_ENABLED")
    purchases = enabled("PURCHASES_ENABLED")
    # The Create screen offers 8 and 12 story pages, with 12 selected by
    # default. A new character and book each use one shared generation slot.
    default_story_pages = 12
    count_limit("DAILY_GENERATION_BUDGET", default_story_pages + 2 if free_beta else 1,
                " (14 required for a character, book and 12 page narrations)" if free_beta else "")
    if free_beta:
        # These guardrails reject a request when current usage reaches the
        # limit. At zero even a new account and an empty queue cannot start.
        for name, default in (
            ("DAILY_JOB_LIMIT_PER_USER", 20),
            ("MAX_PENDING_JOBS_PER_USER", 10),
            ("MAX_PENDING_JOBS", 500),
        ):
            count_limit(name, 1, " (at least one slot required for the first book)", default=default)
        if access_mode != "invite_only":
            invalid.append("GENERATION_ACCESS_MODE (invite_only required for free beta)")
        if not enabled("FREE_PLAN_FIRST_BOOK_TRIAL"):
            invalid.append("FREE_PLAN_FIRST_BOOK_TRIAL (one signup book required for free beta)")
        if purchases:
            invalid.append("PURCHASES_ENABLED (new purchases must be disabled for free beta)")
        if not audio or tts_provider != "google_gemini":
            invalid.append("TTS_PROVIDER (enabled Gemini narration required for free beta)")
    illustration_quality = enabled("ILLUSTRATION_QUALITY_ENABLED")
    photo_processing = enabled("PHOTO_PROCESSING_ENABLED")
    if photo_processing:
        need("PHOTO_ANALYSIS_API_KEY")
        need("PHOTO_ANALYSIS_MODEL")
        if (values.get("PHOTO_ANALYSIS_PROVIDER", "openai") != "openai"
                or values.get("IMAGE_PROVIDER") != "openai"
                or not values.get("IMAGE_MODEL", "").startswith("gpt-image-")):
            invalid.append("PHOTO_PROCESSING_PROVIDER")
    if not illustration_quality:
        invalid.append("ILLUSTRATION_QUALITY_ENABLED (required for release)")
    elif values.get("LLM_PROVIDER") != "openai" or values.get("LLM_MODEL") not in {
        "gpt-5.6-sol", "gpt-6-astra", "gpt-5.6"
    }:
        invalid.append("ILLUSTRATION_QUALITY_MODEL")
    if purchases:
        for name in ("APPLE_BUNDLE_ID", "GOOGLE_PLAY_PACKAGE_NAME",
                     "GOOGLE_RTDN_AUDIENCE", "GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL"):
            need(name)
        try:
            if int(values.get("APPLE_APP_ID", "0")) <= 0:
                invalid.append("APPLE_APP_ID (positive App Store ID required)")
        except ValueError:
            invalid.append("APPLE_APP_ID")
        if values.get("APPLE_NOTIFICATION_ENVIRONMENT", "Production") != "Production":
            invalid.append("APPLE_NOTIFICATION_ENVIRONMENT (Production required for release)")
        if not public_https_endpoint(values.get("GOOGLE_RTDN_AUDIENCE", "")):
            invalid.append("GOOGLE_RTDN_AUDIENCE (public HTTPS push audience required)")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.iam\.gserviceaccount\.com", values.get("GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL", "")):
            invalid.append("GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL")
        google_file = values.get("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "")
        if not (present(values.get("GOOGLE_PLAY_ACCESS_TOKEN"))
                or present(values.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"))
                or (google_file and Path(google_file).is_file())):
            missing.append("GOOGLE_PLAY_AUTH")
    if audio:
        choice("TTS_PROVIDER", {"openai", "google", "google_gemini", "elevenlabs"})
        tts_key = {"openai": "OPENAI_TTS_API_KEY", "google": "GOOGLE_TTS_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}.get(tts_provider)
        stt_key = None
        if not narration_only:
            choice("STT_PROVIDER", {"google", "openai"})
            stt_provider = values.get("STT_PROVIDER", "").strip().lower()
            stt_key = {"google": "GOOGLE_STT_API_KEY", "openai": "STT_API_KEY"}.get(stt_provider)
        for name in (tts_key, stt_key):
            if name:
                need(name)
        if tts_provider == "google_gemini":
            if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", values.get("GOOGLE_GEMINI_TTS_PROJECT", "")):
                invalid.append("GOOGLE_GEMINI_TTS_PROJECT")
            for name in ("GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT", "GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT"):
                count_limit(name, default_story_pages if free_beta else 1,
                            " (12 required for one complete book)" if free_beta else "")
    if pod:
        invalid.append("POD_ORDERING_ENABLED (physical fulfillment is outside this release)")
    return {
        "status": "BLOCKED" if missing or invalid else "CONFIGURED_NOT_VERIFIED",
        "launch_ready": False,
        "configuration_only": True,
        "generation_access_mode": access_mode,
        "missing_or_placeholder": sorted(set(missing)),
        "invalid_configuration": sorted(set(invalid)),
        "features": {"audio": audio, "physical_orders": pod, "new_purchases": purchases,
                     "illustration_quality": illustration_quality,
                     "photo_processing": photo_processing,
                     "kakao_native_share": present(values.get("KAKAO_NATIVE_APP_KEY"))},
        "required_external_evidence": [
            "Live AI authentication, model access and Korean content quality",
            "Photo product: approved child-data processing/retention settings across analysis, image generation and QA; real-photo likeness and fixed-character reuse verification",
            "Existing private media: signed download succeeds, anonymous access denied",
            *(["Device StoreKit/Play purchase, restore and server notification verification"] if purchases else []),
            "Store developer identity, legal consent review and submission acceptance",
            "Public privacy policy, terms of service and support pages open without login; verify release-device links",
            "Production TLS, readiness, backups and restore rehearsal",
        ],
    }


def assess_bundled_policies(root=None):
    """A URL define must not let an unfinished bundled policy ship silently."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    documents = {}
    for slug in ("privacy", "terms"):
        try:
            source = root / f"apps/mobile/assets/legal/{slug}.ko.json"
            document = json.loads(source.read_text())
            effective_date = document.get("effective_date") or ""
            valid_effective_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_date))
            if valid_effective_date:
                date.fromisoformat(effective_date)
            approved = (document.get("publication_status") == "approved"
                        and valid_effective_date
                        and bool(document.get("operator"))
                        and bool(document.get("contact_email"))
                        and bool(document.get("sections")))
            documents[slug] = "approved" if approved else "review_required"
        except (OSError, ValueError, TypeError, AttributeError):
            documents[slug] = "missing_or_invalid"
    return {"ready": all(value == "approved" for value in documents.values()),
            "documents": documents}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON without secret values")
    parser.add_argument("--env-file", action="append", type=Path, default=[],
                        help="Explicit dotenv file; repeat to overlay files. Never executes shell content.")
    parser.add_argument("--check-planned-features", action="store_true",
                        help="Check digital purchase/audio prerequisites without enabling or deploying them")
    parser.add_argument("--free-beta", action="store_true",
                        help="Check invite-only Gemini narration and capacity for one default-length book")
    args = parser.parse_args()
    if args.free_beta and args.check_planned_features:
        parser.error("--free-beta and --check-planned-features are separate release modes")
    values = dict(os.environ)
    for path in args.env_file:
        if not path.is_file():
            parser.error("An explicitly selected environment file does not exist")
        from dotenv import dotenv_values
        values.update({key: value or "" for key, value in dotenv_values(path, interpolate=False).items()})
    if args.check_planned_features:
        # In-memory assessment only. Never mutate runtime configuration or charge anything.
        values.update({name: "true" for name in
                       ("PURCHASES_ENABLED", "AUDIO_FEATURE_ENABLED")})
    result = assess(values, free_beta=args.free_beta)
    result["free_beta"] = args.free_beta
    result["planned_features_only"] = args.check_planned_features
    result["bundled_policy_documents"] = assess_bundled_policies()
    if not result["bundled_policy_documents"]["ready"]:
        result["status"] = "BLOCKED"
        result["invalid_configuration"].append("BUNDLED_POLICY_DOCUMENTS (review and effective date required)")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Release configuration: {result['status']}")
        for name in result["missing_or_placeholder"]:
            print(f" - Missing or placeholder: {name}")
        for name in result["invalid_configuration"]:
            print(f" - Invalid configuration: {name}")
        print("No provider/store calls were made. Configuration presence does not prove launch readiness.")
        if not result["features"]["kakao_native_share"]:
            print("Native Kakao sharing is disabled; ordinary link sharing remains available.")
    return 1 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
