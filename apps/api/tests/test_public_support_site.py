"""No network or accounts: public-site builds require actual approval inputs."""

from email.message import Message
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("public_support_site", ROOT / "scripts/build_public_support_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def fixture_config(tmp_path):
    # Fictional syntax-only fixture, never published or contacted.
    policy = tmp_path / "policy.html"
    policy.write_text('<!doctype html><html lang="ko"><body><h1>승인 흐름 모의 문서</h1></body></html>')
    config = {"site_url": "https://storybook-fixture.org", "support_email": "support@storybook-fixture.org",
              "support_contact_verified": True, "legal_copy_approved": True}
    for name in ("privacy_policy", "terms_of_service"):
        config[name + "_file"] = str(policy)
        config[name + "_sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path, config, policy


@pytest.mark.parametrize("field,value", [
    ("support_contact_verified", False), ("legal_copy_approved", False),
    ("support_email", "support@example.com"), ("support_email", "noreply@storybook-fixture.org"),
    ("support_email", "bad\r\ncontact@storybook-fixture.org"),
    ("support_email", "contact?bcc=someone@storybook-fixture.org"),
    ("site_url", "http://storybook-fixture.org"), ("site_url", "https://127.0.0.1"),
    ("site_url", "https://storybook-fixture.org\n"), ("site_url", "https://bad..org"),
    ("site_url", "https://example.com"), ("privacy_policy_sha256", "0" * 64),
])
def test_invalid_publication_inputs_leave_no_output(tmp_path, field, value):
    config_path, config, _ = fixture_config(tmp_path)
    config[field] = value
    config_path.write_text(json.dumps(config))
    output = tmp_path / "production"
    with pytest.raises(ValueError):
        site.build(config_path, output)
    assert not output.exists()


def test_validated_policy_bytes_are_preserved_and_external_deletion_link_exists(tmp_path):
    config_path, _, policy = fixture_config(tmp_path)
    output = tmp_path / "production"
    result = site.build(config_path, output)
    assert result["publishable"] and not result["deployed"]
    assert (output / "privacy/index.html").read_bytes() == policy.read_bytes()
    assert (output / "terms/index.html").read_bytes() == policy.read_bytes()
    deletion = (output / "delete-account/index.html").read_text()
    assert "mailto:support@storybook-fixture.org?subject=" in deletion
    assert "복구 코드, 비밀번호, 아이 사진을 보내지 마세요" in deletion
    assert "<form" not in deletion and "<script" not in deletion


@pytest.mark.parametrize("failure,reason", [
    (None, None),
    ("old_policy", "PUBLIC_SITE_CONTENT_MISMATCH"),
    ("redirect", "PUBLIC_SITE_REQUEST_FAILED"),
    ("wrong_type", "PUBLIC_SITE_MEDIA_TYPE_INVALID"),
])
def test_verify_published_checks_exact_public_routes(tmp_path, monkeypatch, failure, reason):
    config_path, config, _ = fixture_config(tmp_path)
    output = tmp_path / "production"
    site.build(config_path, output)
    origin = config["site_url"]
    paths = {
        "/": "index.html", "/privacy/": "privacy/index.html", "/terms/": "terms/index.html",
        "/support/": "support/index.html", "/delete-account/": "delete-account/index.html",
        "/site.css": "site.css", "/robots.txt": "robots.txt",
    }
    requested = set()

    class Opener:
        def open(self, url, *, timeout):
            assert timeout > 0 and url.startswith(origin + "/")
            path = url.removeprefix(origin)
            requested.add(path)
            if path == "/privacy/" and failure == "redirect":
                raise HTTPError(url, 302, "Found", {}, None)
            data = (output / paths[path]).read_bytes()
            response = BytesIO(b"outdated" if path == "/privacy/" and failure == "old_policy" else data)
            response.status = 200
            response.headers = Message()
            response.headers["Content-Type"] = {"/site.css": "text/css", "/robots.txt": "text/plain"}.get(path, "text/html; charset=utf-8")
            if path == "/privacy/" and failure == "wrong_type":
                response.headers.replace_header("Content-Type", "text/plain")
            return response

    def opener_factory(proxy, redirect):
        assert proxy.proxies == {}
        assert redirect.redirect_request(None, None, 302, None, None, "https://other-host.org/") is None
        return Opener()

    monkeypatch.setattr(site, "build_opener", opener_factory)
    if reason:
        with pytest.raises(ValueError, match=reason):
            site.verify_published(config_path)
    else:
        assert site.verify_published(config_path) == len(paths)
        assert requested == set(paths)


def test_verify_published_never_contacts_host_for_unapproved_policy(tmp_path, monkeypatch):
    config_path, config, _ = fixture_config(tmp_path)
    config["legal_copy_approved"] = False
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(site, "build_opener", lambda *_: pytest.fail("unexpected network access"))
    with pytest.raises(ValueError, match="APPROVED_POLICY_COPY_REQUIRED"):
        site.verify_published(config_path)


@pytest.mark.parametrize("wrong_url", [True, False])
def test_mobile_policy_drift_blocks_before_network(tmp_path, monkeypatch, wrong_url):
    config_path, config, policy = fixture_config(tmp_path)
    origin = config['site_url']
    bundled = {"privacy": (origin + ("/privacy" if wrong_url else "/privacy/"),
                           policy.read_bytes() if wrong_url else b"older approved copy")}
    monkeypatch.setattr(site, "build_opener", lambda *_: pytest.fail("unexpected network access"))
    expected = "MOBILE_POLICY_URL_MISMATCH" if wrong_url else "MOBILE_BUNDLED_POLICY_MISMATCH"
    with pytest.raises(ValueError, match=expected):
        site.verify_published(config_path, bundled_policies=bundled)


def test_policy_change_after_approval_cannot_be_published(tmp_path):
    config_path, _, policy = fixture_config(tmp_path)
    policy.write_text("changed after approval")
    with pytest.raises(ValueError, match="POLICY_APPROVAL_HASH_MISMATCH"):
        site.build(config_path, tmp_path / "production")


def test_review_document_cannot_publish_even_with_approval_flag_and_matching_hash(tmp_path):
    config_path, config, policy = fixture_config(tmp_path)
    policy.write_text('<!doctype html><html><head><meta name="legal-status" content="review"></head>'
                      '<body>검토본</body></html>')
    for name in ("privacy_policy", "terms_of_service"):
        config[name + "_sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    config_path.write_text(json.dumps(config))
    output = tmp_path / "production"
    with pytest.raises(ValueError, match="POLICY_STILL_IN_REVIEW"):
        site.build(config_path, output)
    assert not output.exists()


@pytest.mark.parametrize("meta", [
    '<meta content="review" name="legal-status">',
    '<META data-id="1" name="legal-status" content="review">',
    '<meta name="legal-status" content="review_required">',
    '<meta name="legal-status">',
    '<meta name="legal-status" content="approved" content="review">',
    '<meta name="legal-status" content="approved"><meta name="legal-status" content="review">',
])
def test_unapproved_policy_status_cannot_be_published_with_matching_hash(tmp_path, meta):
    config_path, config, policy = fixture_config(tmp_path)
    policy.write_text(f'<!doctype html><html><head>{meta}</head><body>검토본</body></html>')
    config["privacy_policy_sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    config["terms_of_service_sha256"] = config["privacy_policy_sha256"]
    config_path.write_text(json.dumps(config))
    output = tmp_path / "production"
    with pytest.raises(ValueError, match="POLICY_STILL_IN_REVIEW"):
        site.build(config_path, output)
    assert not output.exists()


@pytest.mark.parametrize("meta", [
    '',  # External approved documents need not contain our metadata.
    '<meta content="approved" name="legal-status">',
    '<meta name="legal-status" content="approved"><meta name="legal-status" content="approved">',
])
def test_approved_policy_documents_remain_usable(tmp_path, meta):
    config_path, config, policy = fixture_config(tmp_path)
    policy.write_text(f'<!doctype html><html><head>{meta}</head><body>승인 흐름 모의 문서</body></html>')
    config["privacy_policy_sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    config["terms_of_service_sha256"] = config["privacy_policy_sha256"]
    config_path.write_text(json.dumps(config))
    output = tmp_path / "production"
    site.build(config_path, output)
    assert (output / "privacy/index.html").read_bytes() == policy.read_bytes()


def test_preview_omits_contacts_and_policies_and_cannot_claim_publication(tmp_path, monkeypatch):
    config_path, _, _ = fixture_config(tmp_path)
    monkeypatch.setattr(site, "ROOT", tmp_path)
    assets = tmp_path / "apps/public-site"
    assets.mkdir(parents=True)
    (assets / "site.css").write_text("body{color:black}")
    output = tmp_path / "docs/acceptance/preview"
    result = site.build(config_path, output, preview=True)
    assert not result["publishable"] and not result["contact_verified"]
    assert "Disallow: /" in (output / "robots.txt").read_text()
    for page in output.rglob("*.html"):
        text = page.read_text()
        assert "mailto:" not in text
        assert "storybook-fixture.org" not in text
        assert "noindex,nofollow" in text


@pytest.mark.parametrize("active_html", [
    '<script src="https://storybook-fixture.org/tracker.js"></script>',
    '<a href="java&#115;cript:alert(1)">link</a>',
    '<a href="java&#x09;script:alert(1)">link</a>',
])
def test_active_policy_content_is_rejected_even_with_matching_hash(tmp_path, active_html):
    config_path, config, policy = fixture_config(tmp_path)
    policy.write_text(active_html)
    config["privacy_policy_sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="POLICY_ACTIVE_CONTENT_REJECTED"):
        site.build(config_path, tmp_path / "production")
