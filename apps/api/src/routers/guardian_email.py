"""Parent-facing consent link and authenticated request/status endpoints."""

import secrets
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.consent import latest_active_consent
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import APIError
from src.core.guardian_consent_version import guardian_consent_version
from src.models.db import UserConsent
from src.services.guardian_email import approve_guardian_email, guardian_email_record, issue_guardian_email
from src.services.photo_lifecycle import lock_photo_account

router = APIRouter(prefix="/guardian-email")


class GuardianEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254, repr=False)


class GuardianEmailConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    consent: Literal[True]


class GuardianEmailStatus(BaseModel):
    status: Literal["not_required", "needed", "pending", "approved"]


async def pending_approval(db: AsyncSession, owner: str, *, token: str | None = None) -> dict | None:
    record = await guardian_email_record(user_key=owner, token=token)
    if record is None:
        return None
    revoked = await db.scalar(
        select(UserConsent.revoked_at)
        .where(UserConsent.user_key == owner, UserConsent.revoked_at.is_not(None))
        .order_by(UserConsent.revoked_at.desc()).limit(1)
    )
    return None if revoked and revoked >= record["issued_at"] else record


@router.post("", response_model=GuardianEmailStatus)
async def request_guardian_email(
    request: GuardianEmailRequest, db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_user_key),
):
    if not settings.guardian_email_consent_enabled:
        return GuardianEmailStatus(status="not_required")
    if await latest_active_consent(db, owner):
        return GuardianEmailStatus(status="approved")
    guardian_consent_version(owner)  # Confirm that a later grant can be persisted.
    await db.commit()  # No open database transaction during SMTP.
    await issue_guardian_email(owner, request.email.strip())
    return GuardianEmailStatus(status="pending")


@router.get("", response_model=GuardianEmailStatus)
async def get_guardian_email_status(
    db: AsyncSession = Depends(get_db), owner: str = Depends(get_user_key),
):
    if not settings.guardian_email_consent_enabled:
        return GuardianEmailStatus(status="not_required")
    if await latest_active_consent(db, owner):
        return GuardianEmailStatus(status="approved")
    record = await pending_approval(db, owner)
    return GuardianEmailStatus(
        status="approved" if record and record["approved"] else "pending" if record else "needed"
    )


@router.get("/confirm", response_class=HTMLResponse, include_in_schema=False)
async def guardian_email_page():
    if not settings.guardian_email_consent_enabled:
        raise APIError(404, "NOT_FOUND", "동의 요청을 찾을 수 없습니다.")
    nonce = secrets.token_urlsafe(18)
    return HTMLResponse(
        """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 동화책 보호자 동의</title>
<main>
<h1>AI 동화책 보호자 동의</h1>
<p>보호자 본인이 요청한 경우에만 확인해 주세요.</p>
<p>AI 동화책은 서재와 맞춤 동화를 제공하기 위해 아이 프로필, 입력한 별명·연령대·주제, 생성 결과와 독서 기록을 처리합니다.
보호자 이메일은 확인 요청을 보내는 데 사용합니다. 이 확인은 사진 사용 동의를 포함하지 않습니다.</p>
<p>처리 목적과 항목, 외부 처리, 보관 기간, 삭제·철회 방법은
<a href="https://ai-story-book-support.vercel.app/privacy/" target="_blank" rel="noopener noreferrer">개인정보처리방침</a>에서 확인해 주세요.
동의를 거부할 수 있습니다. 동의하지 않으면 아동 정보를 사용하는 기능을 이용할 수 없습니다.</p>
<button type="button" id="agree">법정대리인으로서 동의합니다</button>
<p id="result" role="status"></p>
</main>
<script nonce="NONCE">
const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
const button = document.getElementById('agree');
const result = document.getElementById('result');
if (!/^[A-Za-z0-9_-]{43}$/.test(token)) {
  button.disabled = true;
  result.textContent = '앱에서 확인 메일을 다시 요청해 주세요.';
}
button.addEventListener('click', async () => {
  button.disabled = true;
  try {
    const response = await fetch(location.pathname, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token, consent: true}), credentials: 'omit'
    });
    result.textContent = response.ok ? '동의를 확인했습니다. 앱으로 돌아가 주세요.'
      : '확인할 수 없습니다. 앱에서 새 이메일을 요청해 주세요.';
  } catch {
    result.textContent = '연결을 확인한 뒤 다시 눌러 주세요.';
    button.disabled = false;
  }
});
</script></html>""".replace("NONCE", nonce),
        headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/confirm", response_model=GuardianEmailStatus)
async def confirm_guardian_email(request: GuardianEmailConfirmation, db: AsyncSession = Depends(get_db)):
    invalid = APIError(404, "GUARDIAN_EMAIL_REQUEST_INVALID", "동의 요청이 만료되었거나 변경되었습니다.")
    if not settings.guardian_email_consent_enabled:
        raise invalid
    record = await guardian_email_record(token=request.token)
    if record is None:
        raise invalid
    owner = record["owner"]
    await lock_photo_account(db, owner)
    if await pending_approval(db, owner, token=request.token) is None:
        raise invalid
    if not await approve_guardian_email(request.token, owner):
        raise invalid
    return GuardianEmailStatus(status="approved")
