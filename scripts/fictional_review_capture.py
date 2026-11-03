"""Opt-in fictional acceptance evidence, installed only in a disposable source copy.

Capture the completed book inputs before its QA request, and validated issue codes
after it. Source-photo/portrait analysis adapters are never intercepted. No raw
provider body, credential, storage URL, database row or real-child input is saved.
load_review_input reconstructs these exact bytes/context for a separately guarded
review-only replay; it does not make any provider request.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


class CaptureError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise CaptureError(code)


def private_directory(path, repository_root):
    path, root = Path(path), Path(repository_root).resolve()
    require(path.is_absolute() and path == path.resolve() and path.is_relative_to(root),
            "FICTIONAL_CAPTURE_PATH_INVALID")
    result = subprocess.run(["git", "-C", str(root), "check-ignore", "--quiet", "--", str(path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    require(result.returncode == 0, "FICTIONAL_CAPTURE_REQUIRES_GIT_IGNORE")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    details = os.fstat(fd)
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
        os.close(fd)
        raise CaptureError("FICTIONAL_CAPTURE_REQUIRES_PRIVATE_DIRECTORY")
    return fd


def write_private(fd, filename, data):
    target = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(target, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(fd, filename, value):
    write_private(fd, filename, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def read_private(fd, filename, limit):
    target = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(target, "rb") as stream:
        details = os.fstat(stream.fileno())
        require(stat.S_ISREG(details.st_mode) and stat.S_IMODE(details.st_mode) == 0o600
                and details.st_uid == os.getuid(), "FICTIONAL_CAPTURE_FILE_NOT_PRIVATE")
        data = stream.read(limit + 1)
    require(0 < len(data) <= limit, "FICTIONAL_CAPTURE_FILE_SIZE_INVALID")
    return data


def _context(title, page_texts, image_prompts):
    from src.core.config import settings

    context = {"title": title, "page_texts": page_texts, "image_prompts": image_prompts}
    encoded = json.dumps(context, ensure_ascii=False)
    credentials = [settings.llm_api_key, settings.image_api_key, settings.photo_analysis_api_key]
    require(not any(value and value in encoded for value in credentials), "FICTIONAL_CAPTURE_CREDENTIAL_REJECTED")
    require(not any(marker in encoded.lower() for marker in ("https://", "http://", "data:image", "sk-proj-")),
            "FICTIONAL_CAPTURE_PRIVATE_REFERENCE_REJECTED")
    return context


def wrap_review(original, directory, repository_root, *, expected_images=13):
    """No retries, response substitutions, relaxed deadlines or publication changes."""
    require(expected_images in (5, 13), "FICTIONAL_CAPTURE_IMAGE_COUNT_INVALID")
    root_fd = private_directory(directory, repository_root)
    os.close(root_fd)

    async def captured_review(*, title, page_texts, image_prompts, images, timeout=45.0):
        from src.core.errors import ErrorCode
        from src.services.image_quality import _validate_inputs, BookIllustrationReview

        numbers = _validate_inputs(title, page_texts, image_prompts, images, timeout)
        require(numbers == list(range(expected_images)), "FICTIONAL_CAPTURE_IMAGE_COUNT_INVALID")
        context = _context(title, page_texts, image_prompts)
        root_fd = private_directory(directory, repository_root)
        try:
            for attempt in (1, 2):
                name = f"review-{attempt:02d}"
                try:
                    os.mkdir(name, mode=0o700, dir_fd=root_fd)
                    break
                except FileExistsError:
                    continue
            else:
                raise CaptureError("FICTIONAL_CAPTURE_REVIEW_LIMIT")
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        finally:
            os.close(root_fd)
        try:
            records = []
            for number in numbers:
                data, mime = images[number]
                extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
                filename = f"page-{number:02d}.{extension}"
                write_private(fd, filename, data)
                records.append({"page": number, "file": filename, "mime": mime,
                                "sha256": hashlib.sha256(data).hexdigest()})
            write_json(fd, "input.json", {
                "version": 1, "classification": "fictional_image", "real_child_data": False,
                "source_photos_retained": False, "images": records, **context,
            })
            try:
                result = await original(title=title, page_texts=page_texts, image_prompts=image_prompts,
                                        images=images, timeout=timeout)
                # Saving results cannot turn malformed collaborator output into a pass.
                validated = BookIllustrationReview.model_validate(result.model_dump(mode="json"))
                require([page.page_number for page in validated.pages] == numbers,
                        "FICTIONAL_CAPTURE_REVIEW_INVALID")
                write_json(fd, "review.json", {"status": "validated_response", "review": validated.model_dump(mode="json")})
                return result
            except BaseException as exc:
                code = getattr(exc, "code", None)
                write_json(fd, "review.json", {"status": "review_failed",
                                               "error_code": code.value if isinstance(code, ErrorCode) else "UNKNOWN"})
                raise
        finally:
            os.close(fd)
    return captured_review


def load_review_input(directory, *, repository_root):
    """Restore validated 5- or 13-image QA inputs; no network or source-photo path."""
    from src.services.image_quality import _validate_inputs

    fd = private_directory(directory, repository_root)
    try:
        record = json.loads(read_private(fd, "input.json", 512 * 1024))
        require(record.get("version") == 1 and record.get("classification") == "fictional_image"
                and record.get("real_child_data") is False and record.get("source_photos_retained") is False,
                "REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN")
        require(type(record.get("images")) is list and len(record["images"]) in (5, 13),
                "FICTIONAL_CAPTURE_IMAGE_LIST_INVALID")
        images = {}
        for number, image in enumerate(record["images"]):
            require(type(image) is dict and type(image.get("page")) is int and image["page"] == number,
                    "FICTIONAL_CAPTURE_PAGE_INVALID")
            mime = image.get("mime")
            require(mime in {"image/png", "image/jpeg", "image/webp"}, "FICTIONAL_CAPTURE_MIME_INVALID")
            extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
            require(image.get("file") == f"page-{number:02d}.{extension}", "FICTIONAL_CAPTURE_FILENAME_INVALID")
            data = read_private(fd, image["file"], 8 * 1024 * 1024)
            require(hashlib.sha256(data).hexdigest() == image.get("sha256"), "FICTIONAL_CAPTURE_IMAGE_CHANGED")
            images[number] = (data, mime)
        context = _context(record["title"], {int(k): v for k, v in record["page_texts"].items()},
                           {int(k): v for k, v in record["image_prompts"].items()})
        result = {**context, "images": images}
        _validate_inputs(**result, timeout=45.0)
        return result
    finally:
        os.close(fd)


def install():
    require(os.environ.get("LIVE_FICTIONAL_REVIEW_CAPTURE") == "true"
            and os.environ.get("LIVE_ACCEPTANCE_SOURCE_CLASSIFICATION") == "fictional_image",
            "REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN")
    directory = os.environ.get("LIVE_FICTIONAL_REVIEW_DIRECTORY", "")
    repository_root = os.environ.get("LIVE_ACCEPTANCE_REPOSITORY_ROOT", "")
    require(bool(directory) and bool(repository_root), "FICTIONAL_CAPTURE_CONFIGURATION_MISSING")
    from src.services import image_quality

    require(not getattr(image_quality.review_book_illustrations, "_fictional_capture", False),
            "FICTIONAL_CAPTURE_ALREADY_INSTALLED")
    page_count = os.environ.get("LIVE_ACCEPTANCE_PAGE_COUNT", "12")
    require(page_count in ("4", "12"), "FICTIONAL_CAPTURE_IMAGE_COUNT_INVALID")
    wrapper = wrap_review(image_quality.review_book_illustrations, directory, repository_root,
                          expected_images=int(page_count) + 1)
    wrapper._fictional_capture = True
    image_quality.review_book_illustrations = wrapper
