"""Short-lived email consent requests. Email addresses are not stored here."""

import asyncio
import hashlib
import json
import re
import secrets
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlsplit

from redis.exceptions import RedisError

from src.core.config import read_provider_key_file, settings
from src.core.exceptions import APIError
from src.core.guardian_consent_version import guardian_consent_version
from src.core.rate_limit import rate_limiter
from src.core.utils import utcnow

_TTL = 30 * 60
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def unavailable() -> APIError:
    return APIError(503, "GUARDIAN_EMAIL_UNAVAILABLE", "보호자 이메일 확인을 잠시 사용할 수 없습니다.")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def owner_key(user_key: str) -> str:
    return "guardian-email:account:" + digest(user_key)


def _token_key(token: str) -> str:
    return "guardian-email:token:" + digest(token)


def _mail_config() -> tuple[str, str]:
    try:
        origin = urlsplit(settings.guardian_email_public_origin)
    except ValueError:
        raise unavailable() from None
    if (
        origin.scheme != "https" or not origin.hostname or origin.username or origin.password
        or origin.path not in ("", "/") or origin.query or origin.fragment
        or not settings.guardian_email_smtp_host or not settings.guardian_email_smtp_username
        or not _EMAIL.fullmatch(settings.guardian_email_sender)
    ):
        raise unavailable()
    try:
        password = read_provider_key_file(settings.guardian_email_smtp_password_file)
    except RuntimeError:
        raise unavailable() from None
    return settings.guardian_email_public_origin.rstrip("/"), password


def ensure_guardian_email_ready() -> None:
    _mail_config()
    guardian_consent_version("00000000-0000-4000-8000-000000000000")


def _send_notice(recipient: str, link: str, password: str) -> None:
    message = EmailMessage()
    message["From"] = settings.guardian_email_sender
    message["To"] = recipient
    message["Subject"] = "AI 동화책 보호자 동의 확인"
    message.set_content(
        "AI 동화책의 아동 개인정보 처리 동의 요청입니다.\n"
        "보호자 본인이 요청한 경우 링크를 열어 처리 목적, 수집 항목, 보관·삭제 및 동의 거부 안내를 읽고 직접 동의해 주세요.\n"
        "링크는 30분 동안 유효합니다. 요청하지 않으셨다면 아무 조치도 하지 않아도 됩니다.\n\n"
        f"{link}\n\n개인정보처리방침: https://ai-story-book-support.vercel.app/privacy/\n"
    )
    context = ssl.create_default_context()
    host = settings.guardian_email_smtp_host
    port = settings.guardian_email_smtp_port
    starttls = settings.guardian_email_smtp_security == "starttls"
    connection = (
        smtplib.SMTP(host, port, timeout=10)
        if starttls
        else smtplib.SMTP_SSL(host, port, timeout=10, context=context)
    )
    with connection as smtp:
        if starttls:
            smtp.starttls(context=context)
        smtp.login(settings.guardian_email_smtp_username, password)
        smtp.send_message(message)


async def issue_guardian_email(user_key: str, recipient: str) -> None:
    if not _EMAIL.fullmatch(recipient) or len(recipient) > 254:
        raise APIError(422, "VALIDATION_ERROR", "보호자 이메일 주소를 확인해주세요.")
    origin, password = _mail_config()
    token = secrets.token_urlsafe(32)
    tk = _token_key(token)
    ak = owner_key(user_key)
    record = json.dumps({
        "owner": user_key,
        "issued_at": utcnow().isoformat(),
        "version": settings.consent_current_version,
        "approved": False,
    })
    try:
        redis = await rate_limiter.get_redis()
        async with redis.pipeline(transaction=True) as pipe:
            for key, seconds in (
                ("guardian-email:global", 3600),
                ("guardian-email:recipient:" + digest(recipient.lower()), 600),
                ("guardian-email:sender:" + digest(user_key), 600),
            ):
                pipe.incr(key)
                pipe.expire(key, seconds, nx=True)
            total, _, by_recipient, _, by_owner, _ = await pipe.execute()
        if total > 100 or by_recipient > 3 or by_owner > 3:
            raise APIError(429, "RATE_LIMIT", "잠시 후 보호자 이메일을 다시 요청해주세요.")
        async with redis.pipeline(transaction=True) as pipe:
            pipe.set(tk, record, ex=_TTL)
            pipe.set(ak, tk, ex=_TTL)
            await pipe.execute()
    except RedisError:
        raise unavailable() from None
    try:
        # The secret is in the fragment, which is not sent in GET URLs or referrers.
        await asyncio.to_thread(_send_notice, recipient, f"{origin}/v1/consent/guardian-email/confirm#{token}", password)
    except (OSError, smtplib.SMTPException):
        # A failed delivery must not strand the UI at "check your email".
        # Leave a newer request or a link already accepted by the parent alone.
        try:
            await redis.eval(
                """
                if redis.call('GET', KEYS[1]) ~= KEYS[2] then return 0 end
                local raw = redis.call('GET', KEYS[2])
                if raw and cjson.decode(raw).approved then return 0 end
                return redis.call('DEL', KEYS[1], KEYS[2])
                """,
                2, ak, tk,
            )
        except RedisError:
            pass
        raise unavailable() from None


async def guardian_email_record(*, user_key: str | None = None, token: str | None = None) -> dict | None:
    try:
        redis = await rate_limiter.get_redis()
        if token is not None:
            if not _TOKEN.fullmatch(token):
                return None
            tk = _token_key(token).encode()
        else:
            tk = await redis.get(owner_key(user_key))
        raw = await redis.get(tk) if tk else None
        if not raw:
            return None
        record = json.loads(raw)
        if (
            (user_key is not None and record["owner"] != user_key)
            or await redis.get(owner_key(record["owner"])) != tk
            or record["version"] != settings.consent_current_version
        ):
            return None
        record["issued_at"] = datetime.fromisoformat(record["issued_at"])
        return record
    except (RedisError, TypeError, ValueError, KeyError):
        raise unavailable() from None


async def approve_guardian_email(token: str, user_key: str) -> bool:
    """CAS against the latest request and keep its original expiry."""
    tk = _token_key(token)
    try:
        redis = await rate_limiter.get_redis()
        return bool(await redis.eval(
            """
            if redis.call('GET', KEYS[1]) ~= KEYS[2] then return 0 end
            local raw = redis.call('GET', KEYS[2])
            if not raw then return 0 end
            local r = cjson.decode(raw)
            r.approved = true
            redis.call('SET', KEYS[2], cjson.encode(r), 'KEEPTTL')
            return 1
            """,
            2, owner_key(user_key), tk,
        ))
    except RedisError:
        raise unavailable() from None
