"""The paid diagnostic never follows book URLs or permits broader API requests."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("saved_review", ROOT / "scripts/review_saved_illustrations.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def payload():
    return {"model": "gpt-5.6-sol", "max_output_tokens": 6144, "store": False,
            "text": {"format": {"name": "book_illustration_review"}}}


@pytest.mark.parametrize("updates", [
    {"model": "gpt-6-astra"}, {"max_output_tokens": 6145}, {"store": True},
    {"tools": [{"type": "image_generation"}]}, {"background": True}, {"service_tier": "priority"},
    {"text": {"format": {"name": "story_draft"}}},
])
def test_paid_review_rejects_changed_scope(updates):
    with pytest.raises(ValueError, match="REVIEW_REQUEST_REFUSED"):
        review.validate_request("https://api.openai.com/v1/responses", {**payload(), **updates}, follow_redirects=False)


def test_paid_review_accepts_only_its_fixed_endpoint():
    review.validate_request("https://api.openai.com/v1/responses", payload(), follow_redirects=False)
    with pytest.raises(ValueError, match="REVIEW_ENDPOINT_REFUSED"):
        review.validate_request("https://example.invalid", payload(), follow_redirects=False)
    with pytest.raises(ValueError, match="REVIEW_ENDPOINT_REFUSED"):
        review.validate_request("https://api.openai.com/v1/responses", payload(), follow_redirects=True)


def test_saved_image_symlinks_are_refused(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"test")
    (tmp_path / "page-00.png").symlink_to(source)
    with pytest.raises(ValueError, match="SAVED_ILLUSTRATION_FILE_INVALID"):
        review.owned_file(tmp_path, "page-00.png")


def test_non_acceptance_directory_is_refused(tmp_path):
    with pytest.raises(ValueError, match="ACCEPTANCE_DIRECTORY_REQUIRED"):
        review.load_book(tmp_path)
