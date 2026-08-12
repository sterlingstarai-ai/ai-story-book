"""#9 [H17/H18/G19]: 사진·그림 캐릭터 생성의 서버측 멱등.

두 엔드포인트는 요청 안에서 vision 분석 + (그림은) 시트 이미지 3장을 동기로 수행해 최대
수분이 걸린다. 클라이언트가 타임아웃돼도 서버는 완주하므로 재시도가 중복 캐릭터를 만든다
(서재 오염 + vision·이미지 비용 이중 지출). Job/PodOrder와 동일한 멱등 인프라를 부여한다.

NOTE: 이 두 엔드포인트는 크레딧을 차감하지 않는다(코드 실측). 따라서 '이중 차감'이 아니라
      '재분석·재생성 비용'과 '중복 행'을 검증한다.

false-green 방지: 엔드포인트 자체는 실경로로 통과시키고, mock은 최하위 외부 경계
(vision 분석 서비스 · 스토리지 업로드 · 이미지 생성)에만 건다.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.models.db import Character

PNG = b"\x89PNG\r\n\x1a\n"


def _character_payload(name: str = "토리") -> dict:
    return {
        "name": name,
        "master_description": "a small brave bunny in watercolor",
        "appearance": {
            "age_visual": "6 years old",
            "face": "round face with big eyes",
            "hair": "short white fur",
            "skin": "soft white",
            "body": "small and round",
        },
        "clothing": {
            "top": "red vest",
            "bottom": "blue shorts",
            "shoes": "yellow sneakers",
            "accessories": "a green scarf",
        },
        "personality_traits": ["brave", "kind"],
        "visual_style_notes": "soft pastel",
        "sheet_scene_prompts": ["front pose", "side pose", "happy pose"],
    }


@pytest.fixture
def photo_seams(monkeypatch):
    """외부 경계만 대체: vision 분석 호출 수를 세고, 스토리지/이미지 생성은 무해화."""
    from src.routers import characters as characters_router

    calls = {"photo": 0, "drawing": 0, "sheets": 0}

    async def fake_from_photo(**kwargs):
        calls["photo"] += 1
        return _character_payload()

    async def fake_from_drawing(**kwargs):
        calls["drawing"] += 1
        return _character_payload("두리")

    async def fake_upload(**kwargs):
        return "https://cdn.example.com/characters/src.png"

    async def fake_generate_image(prompt):
        calls["sheets"] += 1
        return "https://cdn.example.com/sheet.png"

    monkeypatch.setattr(
        characters_router.photo_character_service,
        "create_character_from_photo",
        fake_from_photo,
    )
    monkeypatch.setattr(
        characters_router.photo_character_service,
        "create_character_from_drawing",
        fake_from_drawing,
    )
    monkeypatch.setattr(
        characters_router.storage_service, "upload_bytes", fake_upload
    )
    monkeypatch.setattr(characters_router, "generate_image", fake_generate_image)
    return calls


async def _grant_photo_consent(client, headers) -> None:
    """사진 동의를 **실제로** 부여한다.

    R3-4a: 이전 구현은 `{"granted": True, "photo_consent": True}` 라는, DTO에 존재하지
    않는 필드명을 보냈다. pydantic 기본값(extra 무시) 때문에 200이 돌아왔지만 privacy/
    photos/data_processing 은 전부 False 로 저장돼 **아무것도 동의되지 않았다**. 아래
    from-photo 테스트들은 게이트가 꺼져 있어서만 통과하던 false-green이었다.
    이제 DTO는 extra="forbid" 라 오타 payload 는 422 로 즉시 드러난다.
    """
    r = await client.post(
        "/v1/consent",
        json={"privacy": True, "photos": True, "data_processing": True},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["photos"] is True, "동의가 실제로 부여되지 않았다"


# ───────────────────────── DB 계층: 부분 유니크 ─────────────────────────


@pytest.mark.asyncio
async def test_characters_partial_unique_blocks_duplicate_idempotency_key(db_session):
    """같은 (user_key, idempotency_key) 캐릭터 2행 직접 insert → 2번째는 IntegrityError.

    라우터 pre-check를 우회한 동시 더블탭에서 중복 캐릭터를 막는 최종 방어선.
    """
    uk = f"char-uniq-{uuid.uuid4().hex[:6]}"

    def _row(cid: str) -> Character:
        return Character(
            id=cid,
            name="토리",
            master_description="d",
            appearance={},
            clothing={},
            personality_traits=[],
            from_photo=True,
            user_key=uk,
            idempotency_key="dup-key",
        )

    db_session.add(_row(f"c1_{uuid.uuid4().hex[:6]}"))
    await db_session.commit()

    db_session.add(_row(f"c2_{uuid.uuid4().hex[:6]}"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_characters_unique_allows_null_idempotency_key(db_session):
    """키 없는 기존 캐릭터는 부분 유니크 대상이 아니다(다건 공존)."""
    uk = f"char-null-{uuid.uuid4().hex[:6]}"
    for i in range(2):
        db_session.add(
            Character(
                id=f"cn{i}_{uuid.uuid4().hex[:6]}",
                name="미미",
                master_description="d",
                appearance={},
                clothing={},
                personality_traits=[],
                from_photo=False,
                user_key=uk,
                idempotency_key=None,
            )
        )
    await db_session.commit()

    count = (
        await db_session.execute(
            select(func.count()).select_from(Character).where(Character.user_key == uk)
        )
    ).scalar_one()
    assert count == 2


# ───────────────────────── 엔드포인트: 서버측 멱등 ─────────────────────────


@pytest.mark.asyncio
async def test_from_photo_is_idempotent_across_client_retry(
    client, headers, db_session, photo_seams
):
    """같은 시도키 재요청 → 캐릭터 1행 + vision 재분석 없음."""
    await _grant_photo_consent(client, headers)
    h = {**headers, "X-Idempotency-Key": "photo-attempt-1"}
    files = {"photo": ("child.png", PNG, "image/png")}

    first = await client.post("/v1/characters/from-photo", files=files, headers=h)
    second = await client.post("/v1/characters/from-photo", files=files, headers=h)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["character_id"] == second.json()["character_id"], "중복 캐릭터 생성"
    assert photo_seams["photo"] == 1, "재시도에서 vision 재분석 = 비용 이중 지출"

    rows = (
        await db_session.execute(
            select(func.count())
            .select_from(Character)
            .where(Character.idempotency_key == "photo-attempt-1")
        )
    ).scalar_one()
    assert rows == 1


@pytest.mark.asyncio
async def test_from_drawing_is_idempotent_across_client_retry(
    client, headers, db_session, photo_seams
):
    """그림 경로도 동일 — 재시도에서 분석·시트 이미지를 다시 만들지 않는다."""
    await _grant_photo_consent(client, headers)
    h = {**headers, "X-Idempotency-Key": "drawing-attempt-1"}
    files = {"drawing": ("kid.png", PNG, "image/png")}

    first = await client.post("/v1/characters/from-drawing", files=files, headers=h)
    second = await client.post("/v1/characters/from-drawing", files=files, headers=h)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["character_id"] == second.json()["character_id"], "중복 캐릭터 생성"
    assert photo_seams["drawing"] == 1, "재시도에서 그림 재분석 = 비용 이중 지출"
    sheets_after_first = 3
    assert photo_seams["sheets"] == sheets_after_first, (
        "재시도에서 시트 이미지를 다시 생성하면 이미지 비용이 이중 지출된다"
    )

    rows = (
        await db_session.execute(
            select(func.count())
            .select_from(Character)
            .where(Character.idempotency_key == "drawing-attempt-1")
        )
    ).scalar_one()
    assert rows == 1


@pytest.mark.asyncio
async def test_different_keys_create_distinct_characters(
    client, headers, photo_seams
):
    """다른 시도키는 정상적으로 새 캐릭터를 만든다(과잉 dedup 방지)."""
    await _grant_photo_consent(client, headers)
    files = {"photo": ("child.png", PNG, "image/png")}

    a = await client.post(
        "/v1/characters/from-photo",
        files=files,
        headers={**headers, "X-Idempotency-Key": "photo-a"},
    )
    b = await client.post(
        "/v1/characters/from-photo",
        files=files,
        headers={**headers, "X-Idempotency-Key": "photo-b"},
    )
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["character_id"] != b.json()["character_id"]
    assert photo_seams["photo"] == 2


@pytest.mark.asyncio
async def test_without_idempotency_key_behaviour_unchanged(
    client, headers, photo_seams
):
    """키 미전송(구버전 앱)은 기존 동작 그대로 — 매 요청 새 캐릭터."""
    await _grant_photo_consent(client, headers)
    files = {"photo": ("child.png", PNG, "image/png")}

    a = await client.post("/v1/characters/from-photo", files=files, headers=headers)
    b = await client.post("/v1/characters/from-photo", files=files, headers=headers)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["character_id"] != b.json()["character_id"]


@pytest.mark.asyncio
async def test_concurrent_double_tap_absorbs_unique_violation(
    client, headers, db_session, photo_seams, monkeypatch
):
    """두 요청이 동시에 pre-check를 통과한 경우(라우터 조회 미스) — 500이 아니라 멱등 반환.

    부분 유니크가 중복 생성은 이미 막는다. 패배한 요청이 500을 받으면 사용자는 실패로
    인지하고 또 재시도하므로, 승자의 캐릭터를 그대로 돌려준다.
    """
    from src.routers import characters as characters_router

    await _grant_photo_consent(client, headers)
    h = {**headers, "X-Idempotency-Key": "race-key-1"}
    files = {"photo": ("child.png", PNG, "image/png")}

    first = await client.post("/v1/characters/from-photo", files=files, headers=h)
    assert first.status_code == 200, first.text

    # 두 번째 요청에서 pre-check를 강제로 미스시켜 flush가 부분 유니크를 위반하게 한다.
    real_lookup = characters_router._existing_by_idempotency_key
    state = {"miss": True}

    async def flaky_lookup(db, user_key, idempotency_key):
        if state["miss"]:
            state["miss"] = False  # 첫 호출(pre-check)만 미스, 복구 조회는 정상 동작
            return None
        return await real_lookup(db, user_key, idempotency_key)

    monkeypatch.setattr(
        characters_router, "_existing_by_idempotency_key", flaky_lookup
    )

    second = await client.post("/v1/characters/from-photo", files=files, headers=h)
    assert second.status_code == 200, second.text
    assert second.json()["character_id"] == first.json()["character_id"]

    rows = (
        await db_session.execute(
            select(func.count())
            .select_from(Character)
            .where(Character.idempotency_key == "race-key-1")
        )
    ).scalar_one()
    assert rows == 1, "동시 더블탭에서도 캐릭터는 1행"
