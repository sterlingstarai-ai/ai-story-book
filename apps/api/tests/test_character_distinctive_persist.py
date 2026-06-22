"""P0-5 cross-day: distinctive_features가 캐릭터 저장·응답·로드(생성 파이프라인)에 영속되는지."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import Character


@pytest.mark.asyncio
async def test_create_character_persists_and_returns_distinctive_features(
    client: AsyncClient,
    headers: dict,
):
    payload = {
        "name": "토리",
        "master_description": "둥근 얼굴의 용감한 다섯 살 아이, 빨간 안경을 썼다.",
        "appearance": {
            "age_visual": "5세",
            "face": "둥근 얼굴",
            "hair": "짧은 갈색",
            "skin": "밝은 피부",
            "body": "작고 통통",
        },
        "clothing": {
            "top": "파란 멜빵바지",
            "bottom": "없음",
            "shoes": "운동화",
            "accessories": "빨간 안경",
        },
        "personality_traits": ["용감함"],
        "visual_style_notes": "수채화",
        "distinctive_features": ["빨간 안경", "주근깨"],
    }
    res = await client.post("/v1/characters", json=payload, headers=headers)
    assert res.status_code in (200, 201)
    assert res.json()["distinctive_features"] == ["빨간 안경", "주근깨"]


@pytest.mark.asyncio
async def test_load_characters_returns_distinctive_features(
    headers: dict,
    db_session: AsyncSession,
):
    db_session.add(
        Character(
            id="char-df-1",
            name="하나",
            master_description="긴 머리의 친절한 일곱 살 아이",
            appearance={
                "age_visual": "7세",
                "face": "밝은 미소",
                "hair": "긴 머리",
                "skin": "밝은 피부",
                "body": "날씬",
            },
            clothing={
                "top": "원피스",
                "bottom": "없음",
                "shoes": "구두",
                "accessories": "리본",
            },
            personality_traits=["친절"],
            visual_style_notes="카툰",
            distinctive_features=["곱슬머리", "보조개"],
            user_key=headers["X-User-Key"],
        )
    )
    await db_session.commit()

    from src.services.llm import load_characters_from_db

    loaded = await load_characters_from_db(["char-df-1"])
    assert loaded
    assert loaded[0]["distinctive_features"] == ["곱슬머리", "보조개"]


@pytest.mark.asyncio
async def test_from_text_auto_populates_distinctive_features(
    client: AsyncClient,
    headers: dict,
):
    """텍스트 생성 캐릭터는 distinctive_features를 자동으로 채운다(mock 제공자)."""
    res = await client.post(
        "/v1/characters/from-text",
        data={
            "name": "토리",
            "age": "5살",
            "traits": "용감한,호기심",
            "style": "watercolor",
        },
        headers=headers,
    )
    assert res.status_code in (200, 201)
    df = res.json()["distinctive_features"]
    assert isinstance(df, list) and len(df) >= 1
