"""보호자 동의(PIPA/COPPA) 집행 게이트.

아동 사진/얼굴 데이터를 수집하는 기능(사진→캐릭터, reference_image 포함 책 생성)에
서버에 기록된 보호자 동의(UserConsent.photos)를 강제한다.
books.py 의 free-plan 게이트와 동일하게 `settings.testing` 우회 패턴을 따른다.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import AuthorizationError
from src.models.db import UserConsent


def _is_parental_consent_enabled() -> bool:
    if not getattr(settings, "require_parental_consent_enabled", True):
        return False
    if settings.testing and not getattr(
        settings, "require_parental_consent_in_testing", False
    ):
        return False
    return True


async def latest_active_consent(
    db: AsyncSession, user_key: str
) -> Optional[UserConsent]:
    """철회되지 않은 가장 최근 동의 레코드(없으면 None)."""
    result = await db.execute(
        select(UserConsent)
        .where(
            UserConsent.user_key == user_key,
            UserConsent.granted.is_(True),
            UserConsent.revoked_at.is_(None),
        )
        .order_by(UserConsent.created_at.desc())
    )
    return result.scalars().first()


async def require_photo_consent(db: AsyncSession, user_key: str) -> None:
    """아동 사진/얼굴 데이터 수집 전 보호자 동의를 강제한다.

    동의가 없으면 403(AuthorizationError). 테스트/비활성 환경에서는 우회한다.
    """
    if not _is_parental_consent_enabled():
        return
    consent = await latest_active_consent(db, user_key)
    if consent is None or not consent.photos:
        raise AuthorizationError(
            "아동 사진을 사용하려면 보호자 동의가 필요합니다. 설정에서 사진 사용에 동의해주세요."
        )
