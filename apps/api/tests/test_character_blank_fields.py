"""H2 회귀 게이트 — 프로바이더가 빈 문자열을 준 캐릭터 필드.

2026-08-09 중간 E2E: `POST /v1/characters/from-photo` 가 500 을 내면서도 캐릭터 행은
남기고, 그 캐릭터는 단건 조회마저 영구 500 이었다(되살릴 수 없는 고아).

원인: `clothing.get("bottom", "알 수 없음")` — `dict.get` 의 기본값은 **키가 없을 때만**
적용된다. 비전 모델이 `{"bottom": ""}`(키는 있고 값이 빈 문자열)를 주면 그대로 통과해
`CharacterClothing(min_length=1)` 을 위반하고, 그 예외가 **DB 커밋 이후** 응답 직렬화
단계에서 터진다.

mock 전용 결함이 아니다 — 상반신만 나온 아이 사진이면 실제 비전 모델도 하의를 못 보고
빈 값을 돌려주는 것이 자연스럽다. 기존 from-photo 테스트는 모든 필드가 채워진 수제
payload 를 써서 이 경로를 통과한 적이 없다.
"""

import uuid

import pytest
from sqlalchemy import select

from src.models.db import Character
from src.services.character_avatar import generate_character_avatar
from tests import test_character_avatar as avatar_helpers

from src.routers.characters import (
    _build_character_dict,
    _normalize_character_payload,
)


avatar_io = avatar_helpers.avatar_io
source_image = avatar_helpers.source_image


def _blank_provider_payload(name: str = "빈칸토토") -> dict:
    """실제 비전 분석이 돌려줄 수 있는 '부분적으로 빈' 응답."""
    return {
        "name": name,
        "master_description": "둥근 얼굴과 짧은 머리의 아이",
        "appearance": {
            "hair_color": "",
            "hair_style": "",
            "skin_tone": "   ",
            "body_type": "",
            "eye_color": "",
            "distinctive_features": [],
        },
        "clothing": {
            "top": "분홍색 원피스",
            "bottom": "",  # 상반신 사진 → 하의 미관측
            "shoes": "   ",
            "accessories": [],
        },
        "personality_traits": ["활발한"],
        "visual_style_notes": "수채화",
    }


# ------------------------------------------------------------------ 정규화 단위


def test_normalize_fills_blank_strings_not_only_missing_keys():
    """빈 문자열·공백도 기본값으로 채워야 한다(키 부재만이 아니라)."""
    appearance, clothing = _normalize_character_payload(_blank_provider_payload())

    for field, value in {**appearance, **clothing}.items():
        assert isinstance(value, str) and value.strip(), (
            f"{field} 가 빈 값이다: {value!r} — DTO min_length=1 을 위반한다"
        )


def test_normalized_payload_satisfies_dto():
    """정규화 결과가 DTO 검증을 통과한다(응답 직렬화에서 터지지 않는다)."""
    from src.models.dto import CharacterAppearance, CharacterClothing

    appearance, clothing = _normalize_character_payload(_blank_provider_payload())
    CharacterAppearance(**appearance)
    CharacterClothing(**clothing)


@pytest.mark.asyncio
async def test_legacy_blank_row_is_retrievable_via_endpoint(client, db_session):
    """엔드포인트 기준 검증 — 헬퍼만 고치면 단건 조회는 여전히 500 이다.

    `GET /v1/characters/{id}` 는 `_build_character_dict` 를 거치지 않고 DTO 를 직접
    만든다. 헬퍼 단위 테스트만 두면 '고쳤다'고 착각하게 된다(실제로 그랬다).
    """
    user_key = str(uuid.uuid4())
    db_session.add(
        Character(
            id="char_legacy_endpoint",
            name="레거시",
            master_description="설명",
            appearance={"age_visual": "", "face": "", "hair": "", "skin": "", "body": ""},
            clothing={"top": "분홍색 원피스", "bottom": "", "shoes": "알 수 없음",
                      "accessories": "꽃 머리핀"},
            personality_traits=["활발한"],
            visual_style_notes="수채화",
            user_key=user_key,
        )
    )
    await db_session.commit()

    res = await client.get(
        "/v1/characters/char_legacy_endpoint", headers={"X-User-Key": user_key}
    )
    assert res.status_code == 200, (
        f"구버전 빈 값 행의 단건 조회가 실패했다(고아 복구 불가): "
        f"{res.status_code} {res.text[:300]}"
    )
    assert res.json()["clothing"]["bottom"].strip()


def test_build_dict_repairs_legacy_blank_rows():
    """이미 DB에 저장된 빈 값 행(고아)도 조회 가능해야 한다.

    수정 전에 만들어진 캐릭터는 `clothing.bottom == ""` 으로 이미 저장돼 있다. 정규화만
    고치면 그 행들은 여전히 단건 조회에서 500 이다 — 읽기 경로도 방어해야 한다.
    """
    legacy = Character(
        id="char_legacy_blank",
        name="레거시",
        master_description="설명",
        appearance={"age_visual": "", "face": "", "hair": "", "skin": "", "body": ""},
        clothing={"top": "분홍색 원피스", "bottom": "", "shoes": "알 수 없음",
                  "accessories": "꽃 머리핀"},
        personality_traits=["활발한"],
        visual_style_notes="수채화",
        user_key="u",
    )
    payload = _build_character_dict(
        legacy,
        normalized_appearance=legacy.appearance,
        normalized_clothing=legacy.clothing,
    )
    assert payload["clothing"]["bottom"].strip(), "레거시 빈 값이 복구되지 않았다"


# ------------------------------------------------------------------ 엔드포인트


@pytest.fixture()
def blank_photo_boundary(monkeypatch, avatar_io):
    from src.services.character_avatar import photo_character_service

    async def blank(**_kwargs):
        return _blank_provider_payload()

    monkeypatch.setattr(photo_character_service, "create_character_from_photo", blank)
    monkeypatch.setattr(photo_character_service, "create_character_from_drawing", blank)
    return avatar_io


@pytest.mark.asyncio
async def test_from_photo_with_blank_fields_succeeds_and_is_retrievable(
    client, db_session, blank_photo_boundary
):
    user_key = str(uuid.uuid4())
    headers = {"X-User-Key": user_key}
    await client.post(
        "/v1/consent",
        headers=headers,
        json={"privacy": True, "photos": True, "data_processing": True},
    )

    files = {"photo": ("kid.png", source_image(), "image/png")}
    res = await client.post(
        "/v1/characters/from-photo", files=files, data={"name": "빈칸토토"},
        headers=headers,
    )
    assert res.status_code == 200, (
        f"빈 값 필드로 from-photo 가 실패했다(H2 회귀): {res.status_code} {res.text[:400]}"
    )
    character_id = res.json()["character_id"]
    assert await generate_character_avatar(character_id, 1, user_key)

    # 고아가 아니어야 한다 — 단건 조회가 되어야 캐릭터를 실제로 쓸 수 있다.
    single = await client.get(f"/v1/characters/{character_id}", headers=headers)
    assert single.status_code == 200, (
        f"생성된 캐릭터의 단건 조회가 실패했다(고아): {single.status_code} {single.text[:300]}"
    )


@pytest.mark.asyncio
async def test_from_drawing_with_blank_fields_succeeds(
    client, db_session, blank_photo_boundary
):
    user_key = str(uuid.uuid4())
    headers = {"X-User-Key": user_key}
    await client.post(
        "/v1/consent",
        headers=headers,
        json={"privacy": True, "photos": True, "data_processing": True},
    )
    files = {"drawing": ("d.png", source_image(), "image/png")}
    res = await client.post(
        "/v1/characters/from-drawing", files=files, data={"name": "빈칸그림"},
        headers=headers,
    )
    assert res.status_code == 200, (
        f"빈 값 필드로 from-drawing 이 실패했다(H2 회귀): {res.status_code} {res.text[:400]}"
    )
    assert await generate_character_avatar(res.json()["character_id"], 1, user_key)


@pytest.mark.asyncio
async def test_failed_creation_leaves_no_orphan_character(
    client, db_session, monkeypatch, avatar_io
):
    """잘못된 분석은 재조회 가능한 failed 상태가 되며 잘못된 DTO를 저장하지 않는다.

    수정 전에는 커밋이 먼저였기 때문에 '실패 응답 + 남은 캐릭터'가 됐고, 멱등 재시도조차
    같은 지점에서 500 이라 영구히 되살릴 수 없었다.
    """
    from src.routers import characters as characters_router

    async def broken_payload(**_kwargs):
        # name 이 비어 DTO 를 절대 통과할 수 없는 응답
        payload = _blank_provider_payload()
        payload["name"] = ""
        payload["master_description"] = ""
        return payload

    monkeypatch.setattr(
        characters_router.photo_character_service,
        "create_character_from_photo",
        broken_payload,
    )

    user_key = str(uuid.uuid4())
    headers = {"X-User-Key": user_key}
    await client.post(
        "/v1/consent",
        headers=headers,
        json={"privacy": True, "photos": True, "data_processing": True},
    )
    files = {"photo": ("kid.png", source_image(), "image/png")}
    res = await client.post(
        "/v1/characters/from-photo", files=files, headers=headers
    )
    assert res.status_code == 200
    cid = res.json()["character_id"]
    assert not await generate_character_avatar(cid, 1, user_key)
    fetched = await client.get(f"/v1/characters/{cid}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["avatar_status"] == "failed"
    assert fetched.json()["master_description"].strip()
    assert fetched.json()["avatar_retry_allowed"] is True
    assert avatar_io["image"] == 0

    rows = (
        await db_session.execute(
            select(Character).where(Character.user_key == user_key)
        )
    ).scalars().all()
    assert len(rows) == 1 and rows[0].id == cid  # Recoverable state, never an unreadable orphan.
