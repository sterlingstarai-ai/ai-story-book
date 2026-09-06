"""Provider validation evidence must describe our schema, never provider input."""

import json
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, create_model, field_validator
from pydantic_core import PydanticCustomError

from src.core.errors import ErrorCode, LLMError
from src.core.logging import redact_log_data
from src.models.dto import RewriteResult, StoryDraft
from src.services import llm


def valid_story():
    return {
        "title": "작은 도서관", "language": "ko", "target_age": "7-9",
        "moral": "친구를 도와요.",
        "characters": [{"id": "hero", "name": "토리", "role": "main", "brief": "친절한 토끼"}],
        "cover": {"cover_text": "작은 도서관", "scene": "숲속 도서관", "mood": "따뜻함", "camera": "전경"},
        "pages": [
            {"page": number, "text": "친구들이 함께 책을 읽어요.", "scene": "함께 독서하는 모습",
             "mood": "기쁨", "camera": "전경", "characters_present": ["hero"]}
            for number in range(1, 5)
        ],
        "continuity": {"character_consistency_notes": "갈색 토끼", "style_notes_for_images": "수채화"},
    }


@pytest.fixture
def diagnostic_logger(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(llm, "logger", logger)
    return logger


def test_schema_diagnostics_keep_owned_nested_field_and_type_only(diagnostic_logger):
    secret = "PRIVATE_CHILD_NAME_AND_PHOTO_REFERENCE"
    data = valid_story()
    data["pages"][1]["scene"] = secret * 10
    data["pages"][2]["scene"] = secret * 10
    data["cover"]["camera"] = secret * 10
    data["characters"][0][secret] = secret
    data["pages"][0][secret] = secret
    data[secret] = secret
    with pytest.raises(LLMError) as caught:
        llm.parse_json_response(json.dumps(data), StoryDraft)
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None
    event = diagnostic_logger.error.call_args.kwargs
    assert event["schema_model"] == "StoryDraft"
    assert event["schema_error_count"] == 6
    assert {"field_path": "pages[].scene", "validation_type": "string_too_long"} in event["schema_diagnostics"]
    assert {"field_path": "cover.camera", "validation_type": "string_too_long"} in event["schema_diagnostics"]
    assert {"field_path": "characters[]", "validation_type": "extra_forbidden"} in event["schema_diagnostics"]
    assert {"field_path": "pages[]", "validation_type": "extra_forbidden"} in event["schema_diagnostics"]
    assert {"field_path": "$", "validation_type": "extra_forbidden"} in event["schema_diagnostics"]
    assert len(event["schema_diagnostics"]) == 5, "Repeated page errors should be deduplicated"
    assert all(set(item) == {"field_path", "validation_type"} for item in event["schema_diagnostics"])
    assert secret not in str(diagnostic_logger.error.call_args)
    assert secret not in str(caught.value)
    assert redact_log_data(None, None, event)["schema_diagnostics"] == event["schema_diagnostics"]


def test_invalid_json_diagnostics_never_store_response_fragment(diagnostic_logger):
    secret = "PRIVATE_CHILD_UNMODERATED_TEXT"
    with pytest.raises(LLMError) as caught:
        llm.parse_json_response('{"revised_text": "' + secret, RewriteResult)
    event = diagnostic_logger.error.call_args.kwargs
    assert event == {
        "schema_model": "RewriteResult",
        "schema_diagnostics": [{"field_path": "$", "validation_type": "json_invalid"}],
    }
    assert secret not in str(diagnostic_logger.error.call_args)
    assert secret not in str(caught.value)
    assert caught.value.details["raw_output"] is None


def test_unknown_model_or_field_names_are_never_logged(diagnostic_logger):
    secret = "PRIVATE_CHILD_IN_DYNAMIC_SCHEMA_NAME"
    unknown_model = create_model(secret, **{secret: (str, ...)})
    with pytest.raises(LLMError):
        llm.parse_json_response("{}", unknown_model)
    assert diagnostic_logger.error.call_args.kwargs["schema_model"] == "unknown_model"
    assert diagnostic_logger.error.call_args.kwargs["schema_diagnostics"] == [
        {"field_path": "$", "validation_type": "missing"}
    ]
    assert secret not in str(diagnostic_logger.error.call_args)


def test_custom_validation_type_context_and_message_are_not_logged(diagnostic_logger):
    secret = "PRIVATE_CHILD_CUSTOM_ERROR"

    class CustomModel(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def reject(cls, value):
            raise PydanticCustomError(secret, secret + " {private}", {"private": secret})

    with pytest.raises(LLMError) as caught:
        llm.parse_json_response(json.dumps({"value": secret}), CustomModel)
    assert diagnostic_logger.error.call_args.kwargs["schema_diagnostics"] == [
        {"field_path": "$", "validation_type": "unknown_validation_error"}
    ]
    assert secret not in str(diagnostic_logger.error.call_args)
    assert secret not in str(caught.value)


def test_fenced_valid_json_keeps_existing_success_behavior(diagnostic_logger):
    result = llm.parse_json_response('```json\n{"page": 1, "revised_text": "친구와 책을 읽어요."}\n```', RewriteResult)
    assert result.revised_text == "친구와 책을 읽어요."
    diagnostic_logger.error.assert_not_called()


def test_story_prompt_states_all_schema_string_length_bounds():
    schema = StoryDraft.model_json_schema()
    prompt = llm.render_prompt("generate_story.system.jinja2", page_count=8, language="ko", language_name="한국어")

    def field_bounds(node, path=""):
        if "$ref" in node:
            node = schema["$defs"][node["$ref"].rsplit("/", 1)[1]]
        if "maxLength" in node:
            yield path, node.get("minLength"), node["maxLength"]
        for name, child in node.get("properties", {}).items():
            yield from field_bounds(child, f"{path}.{name}" if path else name)
        if "items" in node:
            yield from field_bounds(node["items"], path + "[]")
        for child in node.get("anyOf", []):
            yield from field_bounds(child, path)

    bounds = list(field_bounds(schema))
    assert len(bounds) == 18
    for path, minimum, maximum in bounds:
        expected = f"- {path}: {minimum}-{maximum}자" if minimum else f"- {path}: 최대 {maximum}자 또는 null"
        assert expected in prompt, f"Missing or stale prompt bound for {path}"
    assert "공백과 문장부호 포함" in prompt
    assert "adult도 예외가 없다" in prompt
    assert "pages는 정확히 8개" in prompt
    assert "characters는 1-6명" in prompt
