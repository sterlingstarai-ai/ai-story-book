from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from src.main import app


ROOT_DIR = Path(__file__).resolve().parents[3]
MOBILE_API_CLIENT_PATH = ROOT_DIR / "apps" / "mobile" / "lib" / "services" / "api_client.dart"
SHARED_OPENAPI_PATH = ROOT_DIR / "packages" / "shared" / "schema" / "openapi.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
MOBILE_REQUIRED_FIELDS = {
    "CreateBookResponse": {"job_id", "status"},
    "JobStatus": {"job_id", "status"},
    "BookResult": {"book_id", "title", "cover_image_url", "pages"},
    "PageResult": {"page_number", "text", "image_url"},
    "GenerationWarningInfo": {"code", "message"},
    "CharacterResponse": {
        "character_id",
        "name",
        "master_description",
        "appearance",
        "clothing",
        "personality_traits",
        "created_at",
    },
    "CharacterAppearance": {"age_visual", "face", "hair", "skin", "body"},
    "CharacterClothing": {"top", "bottom", "shoes", "accessories"},
    "BookSummary": {"book_id", "title", "cover_image_url", "target_age", "style", "created_at"},
    "LibraryResponse": {"books"},
    "VocabItem": {"word", "meaning"},
    "ComprehensionQuestion": {"question"},
    "QuizItem": {"question", "options", "answer_index"},
    "ParentGuide": {"summary", "discussion_prompts", "activities"},
    "LearningAssets": {"source_language", "target_language", "title_translation", "parent_guide"},
    "AssetStatusDetail": {"state"},
}
API_CALL_PATTERN = re.compile(
    r"_dio\.(get|post|put|patch|delete)\(\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")",
    re.MULTILINE,
)


def _normalize_path(path: str) -> str:
    parts = []
    for segment in path.strip().strip("/").split("/"):
        if not segment:
            continue
        if "$" in segment:
            parts.append("{param}")
            continue
        if segment.startswith("{") and segment.endswith("}"):
            parts.append("{param}")
            continue
        parts.append(segment)
    return "/" + "/".join(parts)


def _load_shared_openapi_contract() -> dict:
    return json.loads(SHARED_OPENAPI_PATH.read_text(encoding="utf-8"))


def _get_component_schema(spec: dict, schema_name: str) -> dict:
    return spec["components"]["schemas"][schema_name]


def _collect_ref_names(node: object) -> set[str]:
    refs: set[str] = set()

    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            refs.add(ref.rsplit("/", maxsplit=1)[-1])
        for value in node.values():
            refs.update(_collect_ref_names(value))
    elif isinstance(node, list):
        for item in node:
            refs.update(_collect_ref_names(item))

    return refs


def _extract_mobile_api_calls() -> set[tuple[str, str]]:
    source = MOBILE_API_CLIENT_PATH.read_text(encoding="utf-8")
    calls: set[tuple[str, str]] = set()
    for method, dart_string in API_CALL_PATTERN.findall(source):
        path = ast.literal_eval(dart_string)
        calls.add((method.upper(), _normalize_path(path)))
    return calls


def _extract_openapi_operations(spec: dict) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for path, path_item in spec.get("paths", {}).items():
        for method in HTTP_METHODS:
            if method in path_item:
                operations.add((method.upper(), _normalize_path(path)))
    return operations


def test_shared_openapi_contract_is_committed_and_current() -> None:
    assert SHARED_OPENAPI_PATH.exists(), (
        "Shared OpenAPI contract is missing. "
        "Run `python3 scripts/export_openapi_contract.py` to generate it."
    )

    expected = _load_shared_openapi_contract()
    actual = app.openapi()

    assert expected == actual, (
        "Shared OpenAPI contract is stale. "
        "Run `python3 scripts/export_openapi_contract.py` and commit the updated file."
    )


def test_mobile_api_client_matches_openapi_paths_and_methods() -> None:
    mobile_calls = _extract_mobile_api_calls()
    openapi_operations = _extract_openapi_operations(app.openapi())

    missing_operations = sorted(mobile_calls - openapi_operations)

    assert not missing_operations, (
        "Mobile ApiClient calls missing from FastAPI OpenAPI contract: "
        f"{missing_operations}"
    )


def test_mobile_required_response_fields_exist_in_openapi_components() -> None:
    spec = app.openapi()

    for schema_name, required_fields in MOBILE_REQUIRED_FIELDS.items():
        schema = _get_component_schema(spec, schema_name)
        properties = set(schema.get("properties", {}))
        required = set(schema.get("required", []))

        missing_properties = sorted(required_fields - properties)
        missing_required = sorted(required_fields - required)

        assert not missing_properties, (
            f"{schema_name} is missing properties required by the mobile parser: "
            f"{missing_properties}"
        )
        assert not missing_required, (
            f"{schema_name} no longer marks mobile-required fields as required: "
            f"{missing_required}"
        )


def test_openapi_uses_concrete_component_refs_for_nested_mobile_contracts() -> None:
    spec = app.openapi()
    expected_refs = {
        ("JobStatus", "result"): {"BookResult"},
        ("BookResult", "learning_assets"): {"LearningAssets"},
        ("PageResult", "vocab"): {"VocabItem"},
        ("PageResult", "comprehension_questions"): {"ComprehensionQuestion"},
        ("PageResult", "quiz"): {"QuizItem"},
        ("PageResult", "asset_status"): {"AssetStatusDetail"},
    }

    for (schema_name, property_name), expected in expected_refs.items():
        schema = _get_component_schema(spec, schema_name)
        property_schema = schema["properties"][property_name]
        refs = _collect_ref_names(property_schema)
        missing_refs = sorted(expected - refs)

        assert not missing_refs, (
            f"{schema_name}.{property_name} should reference {expected}, "
            f"but OpenAPI only exposes {sorted(refs)}"
        )


def test_inpaint_contract_declares_409_unsupported() -> None:
    """L14: 인페인트 경로가 409(INPAINT_UNSUPPORTED)를 계약에 명세한다."""
    spec = app.openapi()
    inpaint_op = None
    for path, item in spec["paths"].items():
        if path.endswith("/inpaint") and "post" in item:
            inpaint_op = item["post"]
            break
    assert inpaint_op is not None, "inpaint POST 경로를 찾을 수 없음"
    assert "409" in inpaint_op.get("responses", {}), (
        "inpaint 409(INPAINT_UNSUPPORTED) 응답이 계약에 노출되지 않음"
    )
