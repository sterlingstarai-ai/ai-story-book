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
    """사진 게이트 통과 여부 — '가장 최근 비철회 행'이 **granted 이면서 photos** 인가.

    선필터가 아니라 '가장 최근 한 행'을 보는 이유: photos=True 옛 행이 이후의 photos=False
    재-grant에 가려지지 않으면 해제가 무력화된다(누적 레코드 비정합).

    R1-7: 여기에 `granted`를 **결합**한다. granted 는 필수 동의(privacy+data_processing)
    충족을 뜻하는데, 이걸 빼면 `{privacy:false, data_processing:false, photos:true}` 라는
    photos-only 행이 게이트를 통과해 **필수 보호자 동의 없이 아동 사진을 수집**하게 된다
    (PIPA/COPPA에서 photos 는 필수 동의의 하위 항목이지 대체재가 아니다).
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
    return latest is not None and bool(latest.granted) and bool(latest.photos)


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
