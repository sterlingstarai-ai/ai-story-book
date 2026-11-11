"""Account-bound proof carried by the existing consent backup journal."""

import base64

from src.core.config import settings
from src.core.exceptions import APIError
from src.services.account_scope import AccountScopeUnavailable, derive_account_scope

GUARDIAN_EMAIL_PREFIX = "g3-"


def guardian_consent_version(user_key: str) -> str:
    try:
        scope = derive_account_scope(
            owner=user_key,
            namespace=f"guardian-email-{settings.consent_current_version}",
            key_path=settings.account_scope_key_file,
            expected_sha256=settings.account_scope_key_sha256,
        )
    except AccountScopeUnavailable:
        raise APIError(503, "GUARDIAN_EMAIL_UNAVAILABLE", "보호자 동의 확인을 잠시 사용할 수 없습니다.") from None
    return GUARDIAN_EMAIL_PREFIX + base64.urlsafe_b64encode(bytes.fromhex(scope[:24])).decode()
