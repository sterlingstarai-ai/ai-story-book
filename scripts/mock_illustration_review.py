"""Disposable mock QA startup injection; never imported by the production app.

This deterministic double validates the complete image/context input and returns
one explicit empty finding list per page. It does not inspect illustration
semantics and is not evidence of live vision accuracy or content quality.
"""

import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import re
import shutil
import stat
import sys


MARKER_NAME = "STORYBOOK_MOCK_QA"
MARKER_VALUE = "illustration-review-v1"
REVIEW_INVITATIONS_ENV = "STORYBOOK_LOCAL_REVIEW_INVITATIONS_FILE"
MODULE_NAME = "src.services.image_quality"
STARTUP_SOURCE = """import sys
try:
    from mock_illustration_review import install
    install()
except Exception:
    sys.stderr.write("Mock QA startup rejected its configuration.\\n")
    raise SystemExit(78)
"""


def _authorized_environment() -> bool:
    return (
        os.environ.get(MARKER_NAME) == MARKER_VALUE
        and os.environ.get("LLM_PROVIDER") == "mock"
        and os.environ.get("IMAGE_PROVIDER") == "mock"
    )


def _review_invitation_ids(path: Path) -> frozenset[str]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
                return frozenset()
            data = file.read(4097)
        if len(data) > 4096:
            return frozenset()
        entries = data.decode("ascii").split()
    except (OSError, UnicodeError):
        return frozenset()
    return frozenset(entries) if all(re.fullmatch(r"[0-9a-f]{64}", item) for item in entries) else frozenset()


def _install_review_invites(path: Path) -> None:
    if (os.name != "posix" or not _authorized_environment()
            or os.environ.get("TESTING", "").lower() != "false" or not path.is_absolute()):
        raise RuntimeError("MOCK_QA_INVITATIONS_CONFIGURATION_REQUIRED")
    from src.core import generation_access

    original = generation_access.generation_access_allowed

    def allowed(user_key):
        if original(user_key):
            return True
        if not user_key or not generation_access.generation_invitation_supported():
            return False
        return generation_access.generation_identity_hash(user_key) in _review_invitation_ids(path)

    generation_access.generation_access_allowed = allowed


def _patch(module) -> None:
    # conftest imports settings after overriding TESTING. Do not turn ordinary
    # pytest checks into a patched release service or import settings too early.
    if module.settings.testing:
        return
    if not (
        _authorized_environment()
        and module.settings.llm_provider == "mock"
        and module.settings.image_provider == "mock"
        and module.settings.illustration_quality_enabled
    ):
        raise RuntimeError("MOCK_QA_CONFIGURATION_REQUIRED")

    def configured():
        return (
            _authorized_environment()
            and module.settings.llm_provider == "mock"
            and module.settings.image_provider == "mock"
            and module.settings.illustration_quality_enabled
        )

    async def review(
        *, title, page_texts, image_prompts, images,
        timeout=module.REVIEW_TIMEOUT_SECONDS,
    ):
        if not configured():
            raise RuntimeError("MOCK_QA_CONFIGURATION_REQUIRED")
        numbers = module._validate_inputs(title, page_texts, image_prompts, images, timeout)
        result = module.BookIllustrationReview(pages=[
            module.IllustrationPageReview(page_number=number, issues=[])
            for number in numbers
        ])
        module.logger.info("Mock QA illustration review; not live vision", page_count=len(numbers))
        return result

    module.review_provider_configured = configured
    module.review_book_illustrations = review


class _ReviewLoader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original

    def create_module(self, spec):
        return self.original.create_module(spec)

    def exec_module(self, module):
        self.original.exec_module(module)
        _patch(module)


class _ReviewFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != MODULE_NAME:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None or spec.loader is None:
            raise RuntimeError("MOCK_QA_REVIEW_MODULE_MISSING")
        spec.loader = _ReviewLoader(spec.loader)
        return spec


def install() -> None:
    """Install only for an explicitly marked, all-mock disposable process."""
    if not _authorized_environment():
        raise RuntimeError("MOCK_QA_CONFIGURATION_REQUIRED")
    # PG pytest's conftest sets this false; its TESTING=false Celery child must
    # restore the stricter gate before settings loads. No production gate is disabled.
    if os.environ.get("TESTING", "").lower() == "false":
        os.environ["ILLUSTRATION_QUALITY_ENABLED"] = "true"
    if review_file := os.environ.get(REVIEW_INVITATIONS_ENV):
        _install_review_invites(Path(review_file))
    if MODULE_NAME in sys.modules:
        _patch(sys.modules[MODULE_NAME])
    elif not any(isinstance(finder, _ReviewFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _ReviewFinder())
    if archive := os.environ.get("STORYBOOK_LOCAL_REVIEW_ARCHIVE"):
        provider = os.environ.get("TTS_PROVIDER")
        if os.environ.get("TESTING", "").lower() != "false" or provider not in {"google_gemini", "openai_realtime"}:
            raise RuntimeError("MOCK_QA_ARCHIVE_CONFIGURATION_REQUIRED")
        from replay_review_archive import REVIEW_REALTIME_KEY, install_archive_replay

        if provider == "openai_realtime" and os.environ.get("OPENAI_TTS_API_KEY") != REVIEW_REALTIME_KEY:
            raise RuntimeError("MOCK_QA_ARCHIVE_CONFIGURATION_REQUIRED")
        install_archive_replay(Path(archive), provider)


def write_startup_loader(directory: Path) -> None:
    """Copy the test-only hook into an owned temporary Python startup directory."""
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), directory / "mock_illustration_review.py")
    (directory / "sitecustomize.py").write_text(STARTUP_SOURCE)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: mock_illustration_review.py <owned-startup-directory>")
    write_startup_loader(Path(sys.argv[1]))
