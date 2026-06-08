"""보호자 동의(PIPA/COPPA) 집행 게이트.

아동 사진/얼굴 데이터를 수집·재사용하는 기능(사진→캐릭터, 그 캐릭터로 책/시리즈 생성,
reference_image 포함 책 생성)에 서버에 기록된 보호자 동의(UserConsent.photos)를 강제한다.
books.py 의 free-plan 게이트와 동일하게 `settings.testing` 우회 패턴을 따른다.
"""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import AuthorizationError
from src.models.db import Character, UserConsent


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
    """철회되지 않은 가장 최근 '필수 동의(granted)' 레코드. 동률 시 id로 결정적 tie-break."""
    result = await db.execute(
        select(UserConsent)
        .where(
            UserConsent.user_key == user_key,
            UserConsent.granted.is_(True),
            UserConsent.revoked_at.is_(None),
        )
        .order_by(UserConsent.created_at.desc(), UserConsent.id.desc())
    )
    return result.scalars().first()


async def _has_active_photo_consent(db: AsyncSession, user_key: str) -> bool:
    """가장 최근(철회 안 된) 동의 레코드의 photos 동의 여부.

    granted 와 독립적으로 평가한다. granted 는 '필수 동의(privacy+data_processing)' 충족만
    의미하므로, photos 동의를 granted 로 선필터하면 누적 레코드에서 게이트가 photos=True 행을
    못 보는 비정합이 생긴다. 따라서 photos 는 별도로 '가장 최근 비철회 행' 기준으로 판단한다.
    """
    result = await db.execute(
        select(UserConsent)
        .where(
            UserConsent.user_key == user_key,
            UserConsent.revoked_at.is_(None),
        )
        .order_by(UserConsent.created_at.desc(), UserConsent.id.desc())
    )
    latest = result.scalars().first()
    return latest is not None and bool(latest.photos)


async def require_photo_consent(db: AsyncSession, user_key: str) -> None:
    """아동 사진/얼굴 데이터 수집·재사용 전 보호자 동의를 강제한다(미동의 시 403)."""
    if not _is_parental_consent_enabled():
        return
    if not await _has_active_photo_consent(db, user_key):
        raise AuthorizationError(
            "아동 사진을 사용하려면 보호자 동의가 필요합니다. 설정에서 사진 사용에 동의해주세요."
        )


async def uses_photo_derived_character(
    db: AsyncSession, user_key: str, character_ids: List[Optional[str]]
) -> bool:
    """주어진 character_id 중 사진/그림 파생(from_photo) 캐릭터가 있는지."""
    ids = [c for c in (character_ids or []) if c]
    if not ids:
        return False
    result = await db.execute(
        select(Character.id).where(
            Character.user_key == user_key,
            Character.id.in_(ids),
            Character.from_photo.is_(True),
        )
    )
    return result.first() is not None


async def require_consent_for_characters(
    db: AsyncSession, user_key: str, character_ids: List[Optional[str]]
) -> None:
    """사진 파생 캐릭터를 사용할 때만 동의를 강제(텍스트 캐릭터는 게이트하지 않음)."""
    if not _is_parental_consent_enabled():
        return
    if await uses_photo_derived_character(db, user_key, character_ids):
        await require_photo_consent(db, user_key)
