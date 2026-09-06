"""Malformed AI characters must not survive a failed creation response."""

import copy
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError, get_backoff, get_retry_count
from src.models.db import Character
from src.services import llm, photo_character
from src.services.photo_character import PhotoCharacterService, validate_text_character


def rabbit_payload():
    return {
        "name": "토리",
        "master_description": "A small white rabbit with long ears, a blue vest and a red scarf.",
        "appearance": {
            "age_visual": "어린 토끼",
            "face": "분홍 코와 둥근 볼",
            "hair": None,
            "skin": "하얀 털",
            "body": "작은 토끼 몸과 긴 귀",
        },
        "clothing": {
            "top": "파란 조끼",
            "bottom": "  ",
            "shoes": None,
            "accessories": ["빨간 목도리"],
        },
        "personality_traits": ["친절한", "호기심 많은"],
        "visual_style_notes": "부드러운 수채화",
        "distinctive_features": ["하얀 털", "긴 귀", "빨간 목도리"],
    }


FORM = {"name": "토리", "age": "4살", "traits": "흰 토끼,파란 조끼,빨간 목도리", "style": "watercolor"}


@pytest.fixture
def anthropic_stub(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    call = AsyncMock(return_value=rabbit_payload())
    monkeypatch.setattr(photo_character.photo_character_service, "_generate_text_character_anthropic", call)
    sleep = AsyncMock()
    monkeypatch.setattr(photo_character.asyncio, "sleep", sleep)
    return call, sleep


@pytest.mark.asyncio
async def test_animal_character_is_validated_persisted_and_readable(client, headers, db_session, anthropic_stub):
    call, sleep = anthropic_stub
    response = await client.post("/v1/characters/from-text", data=FORM, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["appearance"]["hair"] == "없음"
    assert data["appearance"]["skin"] == "하얀 털"
    assert data["clothing"] == {"top": "파란 조끼", "bottom": "없음", "shoes": "없음", "accessories": "빨간 목도리"}
    assert data["distinctive_features"] == rabbit_payload()["distinctive_features"]
    row = await db_session.get(Character, data["character_id"])
    assert row.appearance == data["appearance"]
    assert row.clothing == data["clothing"]
    loaded = await client.get(f"/v1/characters/{row.id}", headers=headers)
    assert loaded.status_code == 200
    assert loaded.json()["appearance"] == data["appearance"]
    call.assert_awaited_once()
    sleep.assert_not_awaited()
    prompt = call.await_args.args[0]
    for contract in ("동물을 지정하면", "사람 아이로 바꾸지", "배열이 아닌 한 문자열", "10~400자", "face/hair 각각 1~120자", "skin/body 각각 1~80자", "각각 1~80자", "1~200자"):
        assert contract in prompt


@pytest.mark.asyncio
async def test_schema_retry_recovers_without_persisting_bad_first_attempt(client, headers, db_session, anthropic_stub):
    call, sleep = anthropic_stub
    invalid = rabbit_payload()
    invalid["appearance"]["face"] = "가" * 121
    call.side_effect = [invalid, rabbit_payload()]
    response = await client.post("/v1/characters/from-text", data=FORM, headers=headers)
    assert response.status_code == 200
    assert call.await_count == 2
    sleep.assert_awaited_once_with(get_backoff(ErrorCode.LLM_JSON_INVALID, 0))
    assert await db_session.scalar(select(func.count()).select_from(Character)) == 1
    assert call.await_args_list[0] == call.await_args_list[1]


@pytest.mark.asyncio
async def test_exhausted_schema_failure_has_no_row_and_only_owned_diagnostics(
    client, headers, db_session, anthropic_stub, monkeypatch,
):
    call, sleep = anthropic_stub
    secret = "PRIVATE_CHILD_PAYLOAD_AND_PROVIDER_TOKEN"
    invalid = rabbit_payload()
    invalid["clothing"]["accessories"] = [{secret: secret}]
    invalid["appearance"][secret] = secret
    call.return_value = invalid
    diagnostic_logger = Mock()
    service_logger = Mock()
    monkeypatch.setattr(llm, "logger", diagnostic_logger)
    monkeypatch.setattr(photo_character, "logger", service_logger)
    response = await client.post("/v1/characters/from-text", data=FORM, headers=headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_JSON_INVALID"
    assert await db_session.scalar(select(func.count()).select_from(Character)) == 0
    assert call.await_count == get_retry_count(ErrorCode.LLM_JSON_INVALID) + 1
    assert sleep.await_count == get_retry_count(ErrorCode.LLM_JSON_INVALID)
    logs = repr(diagnostic_logger.mock_calls) + repr(service_logger.mock_calls)
    assert secret not in logs + response.text
    assert "clothing.accessories" in logs
    assert "string_type" in logs
    assert "appearance" in logs
    assert "extra_forbidden" in logs


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["missing_face", "missing_clothing", "overlong_shoes", "object_accessory", "extra_key"])
async def test_router_revalidates_adapter_output_before_any_write(client, headers, db_session, monkeypatch, defect):
    payload = rabbit_payload()
    if defect == "missing_face":
        payload["appearance"].pop("face")
    elif defect == "missing_clothing":
        payload.pop("clothing")
    elif defect == "overlong_shoes":
        payload["clothing"]["shoes"] = "가" * 81
    elif defect == "object_accessory":
        payload["clothing"]["accessories"] = {"unexpected": "scarf"}
    else:
        payload["untrusted_extra"] = "do not log"
    monkeypatch.setattr(photo_character.photo_character_service, "create_character_from_text", AsyncMock(return_value=payload))
    response = await client.post("/v1/characters/from-text", data=FORM, headers=headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_JSON_INVALID"
    assert await db_session.scalar(select(func.count()).select_from(Character)) == 0
    assert "untrusted_extra" not in response.text


@pytest.mark.asyncio
async def test_invalid_json_is_bounded_and_not_echoed(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    secret = "PRIVATE_MALFORMED_RESPONSE"
    service = PhotoCharacterService()
    call = AsyncMock(side_effect=json.JSONDecodeError("Invalid private payload", secret, 0))
    monkeypatch.setattr(service, "_generate_text_character_anthropic", call)
    sleep = AsyncMock()
    monkeypatch.setattr(photo_character.asyncio, "sleep", sleep)
    with pytest.raises(LLMError) as caught:
        await service.create_character_from_text("토리", "4살", ["토끼"])
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None
    assert secret not in str(caught.value)
    assert call.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_provider_billing_error_does_not_retry_or_persist(client, headers, db_session, anthropic_stub):
    call, sleep = anthropic_stub
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(402, request=request, text="PRIVATE_PROVIDER_BILLING_DETAIL")
    call.side_effect = httpx.HTTPStatusError("PRIVATE_PROVIDER_BILLING_DETAIL", request=request, response=response)
    result = await client.post("/v1/characters/from-text", data=FORM, headers=headers)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "UNKNOWN"
    assert "PRIVATE_PROVIDER_BILLING_DETAIL" not in result.text
    assert await db_session.scalar(select(func.count()).select_from(Character)) == 0
    call.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_name_bound_rejects_before_provider_call(client, headers, anthropic_stub):
    call, _ = anthropic_stub
    response = await client.post("/v1/characters/from-text", data={**FORM, "name": "가" * 41}, headers=headers)
    assert response.status_code == 422
    call.assert_not_awaited()


def test_normalization_does_not_mutate_input_or_invent_missing_fields():
    payload = rabbit_payload()
    original = copy.deepcopy(payload)
    validate_text_character(payload)
    assert payload == original
    payload["appearance"].pop("hair")
    with pytest.raises(LLMError):
        validate_text_character(payload)
