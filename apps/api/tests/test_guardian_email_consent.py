"""Exercise the actual Redis request/approval protocol and HTTP consent gate."""

import hashlib
import os
from unittest.mock import MagicMock
from urllib.parse import urlsplit

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from src.core.config import settings
from src.core.rate_limit import rate_limiter
from src.models.db import UserConsent
from src.services import guardian_email


def test_guardian_mail_requires_starttls_before_authentication(monkeypatch):
    connection = MagicMock()
    smtp = connection.__enter__.return_value
    smtp.starttls.side_effect = guardian_email.smtplib.SMTPNotSupportedError
    monkeypatch.setattr(guardian_email.smtplib, "SMTP", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(settings, "guardian_email_smtp_security", "starttls")
    monkeypatch.setattr(settings, "guardian_email_smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "guardian_email_smtp_port", 587)
    monkeypatch.setattr(settings, "guardian_email_sender", "noreply@example.test")

    with pytest.raises(guardian_email.smtplib.SMTPNotSupportedError):
        guardian_email._send_notice("parent@example.test", "https://example.test", "test-only")

    context = smtp.starttls.call_args.kwargs["context"]
    assert context.check_hostname
    smtp.login.assert_not_called()
    smtp.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_guardian_email_is_account_bound_and_withdrawal_invalidates_it(
    client, db_session, monkeypatch, tmp_path,
):
    redis_url = os.getenv("E2E_GUARDIAN_REDIS_URL")
    if not redis_url:
        pytest.skip("Requires a disposable Redis for the email protocol")
    redis = Redis.from_url(redis_url)

    async def get_redis():
        return redis

    monkeypatch.setattr(rate_limiter, "get_redis", get_redis)
    monkeypatch.setattr(settings, "guardian_email_consent_enabled", True)
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    monkeypatch.setattr(settings, "account_scope_key_file", str(key))
    monkeypatch.setattr(settings, "account_scope_key_sha256", hashlib.sha256(key.read_bytes()).hexdigest())
    monkeypatch.setattr(guardian_email, "_mail_config", lambda: ("https://example.test", "fake"))
    messages = []
    monkeypatch.setattr(guardian_email, "_send_notice", lambda to, link, _: messages.append((to, link)))
    owner = {"X-User-Key": "70000000-0000-4000-8000-000000000001"}
    other = {"X-User-Key": "70000000-0000-4000-8000-000000000002"}
    decision = {"privacy": True, "data_processing": True, "photos": False}
    path = "/v1/consent"
    email = path + "/guardian-email"
    try:
        assert (await client.post(path, headers=owner, json=decision)).status_code == 403
        def failed_send(*_args):
            raise OSError("Synthetic SMTP failure")

        with monkeypatch.context() as smtp_failure:
            smtp_failure.setattr(guardian_email, "_send_notice", failed_send)
            assert (await client.post(email, headers=owner, json={"email": "parent@example.test"})).status_code == 503
            assert (await client.get(email, headers=owner)).json()["status"] == "needed"
        assert (await client.post(email, headers=owner, json={"email": "parent@example.test"})).json()["status"] == "pending"
        link = urlsplit(messages[-1][1])
        assert not link.query and link.fragment
        page = await client.get(link.path)
        assert page.status_code == 200 and page.headers["referrer-policy"] == "no-referrer"
        assert (await client.get(email, headers=owner)).json()["status"] == "pending"
        assert (await client.post(link.path, json={"token": link.fragment, "consent": False})).status_code == 422
        assert (await client.post(link.path, json={"token": link.fragment, "consent": True})).status_code == 200
        assert (await client.get(email, headers=other)).json()["status"] == "needed"
        assert (await client.post(path, headers=other, json=decision)).status_code == 403
        assert (await client.post(path, headers=owner, json={**decision, "photos": True})).status_code == 403
        response = await client.post(path, headers=owner, json=decision)
        assert response.status_code == 200 and response.json()["granted"] is True
        row = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == owner["X-User-Key"]))
        assert row.consent_version.startswith("g3-")
        assert response.json()["consent_version"] != row.consent_version
        assert (await client.post(path, headers=other, json={**decision, "consent_version": row.consent_version})).status_code == 422
        assert (await client.post(path + "/revoke", headers=owner)).status_code == 200
        assert (await client.post(link.path, json={"token": link.fragment, "consent": True})).status_code == 404
        assert (await client.post(path, headers=owner, json=decision)).status_code == 403
    finally:
        await redis.aclose()
