"""Native capture validation never starts or modifies a user's simulator."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("store_review_capture", ROOT / "scripts/capture_store_review.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
DEVICE = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("name,state", [("User Phone", "Booted"), ("AIStoryBookReview-test", "Shutdown")])
def test_only_owned_already_booted_devices_are_allowed(monkeypatch, name, state):
    monkeypatch.setattr(capture.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps(
        {"devices": {"runtime": [{"udid": DEVICE, "name": name, "state": state}]}})))
    with pytest.raises(ValueError, match="OWNED_BOOTED_REVIEW_DEVICE_REQUIRED"):
        capture.verify_device(DEVICE)


def test_capture_preserves_native_size_and_uses_only_screenshot(monkeypatch, tmp_path):
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        Image.new("RGB", (1320, 2868), "white").save(command[-1], "JPEG")

    monkeypatch.setattr(capture.subprocess, "run", run)
    result = capture.capture(DEVICE, "iphone-69", tmp_path / "stage.jpg")
    assert (result["width"], result["height"]) == (1320, 2868)
    assert commands[0][2:6] == ["io", DEVICE, "screenshot", "--type=jpeg"]


def test_small_preview_cannot_be_mislabeled_as_store_capture(monkeypatch, tmp_path):
    monkeypatch.setattr(capture.subprocess, "run", lambda command, **kw:
                        Image.new("RGB", (402, 874), "white").save(command[-1], "JPEG"))
    with pytest.raises(ValueError, match="NATIVE_STORE_DIMENSIONS_MISMATCH"):
        capture.capture(DEVICE, "iphone-69", tmp_path / "stage.jpg")
