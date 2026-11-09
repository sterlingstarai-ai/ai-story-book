#!/usr/bin/env python3
"""Explicitly paid one-book acceptance against isolated real dependencies.

One fictional character and one 4-, 8-, or 12-page book per invocation. The
illustration release gate is enabled. A shared HTTP journal caps all processes
at 16 LLM requests and 7, 11, or 16 image requests, including failed attempts
and repairs. This is one acceptance sample, not the full A1 quality gate.
Only already-cached local Docker images are used. No production env is loaded.
The default is fully synthetic. An optional private reader profile supplies a
protagonist name and optionally gender/age. Appearance stays fictional; no photos are used.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid
import unicodedata
import wave

from dotenv import dotenv_values
import httpx
from PIL import Image

from live_acceptance_guard import (
    ACCEPTANCE_PAGE_COUNTS, IMAGE_MODELS, JOURNAL_VERSION, LLM_MODELS, LLM_TOKEN_LIMITS,
    request_limits,
)
from run_runtime_e2e import (
    ROOT, IMAGES, GateFailure, clean_environment, first_book_trial_environment,
    free_port, port_for, require, run, stop_process_group,
)

# Stable public JobStatus.error.code values only. Never copy an error message or
# an arbitrary uppercase provider value into acceptance reports.
_JOB_ERROR_CODES = frozenset({
    "AI_PROVIDER_UNAVAILABLE", "SAFETY_INPUT", "SAFETY_OUTPUT", "LLM_TIMEOUT", "LLM_JSON_INVALID", "IMAGE_TIMEOUT",
    "IMAGE_RATE_LIMIT", "IMAGE_FAILED", "IMAGE_QUALITY_FAILED", "STORAGE_UPLOAD_FAILED",
    "CHARACTER_APPROVAL_REQUIRED", "CHARACTER_REFERENCE_UNAVAILABLE",
    "PHOTO_PROCESSING_UNAVAILABLE", "DB_WRITE_FAILED", "QUEUE_FAILED", "UNKNOWN",
})


def job_error_code(job):
    error = job.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code in _JOB_ERROR_CODES else None


def runtime_config(values, *, llm_values=None, llm_model=None, image_model=None):
    """Resolve explicit acceptance settings without changing the two-call smoke.

    An optional LLM-only file is a separate credential source. In particular,
    selecting GPT must never send the base file's Anthropic LLM_API_KEY to it.
    """
    source = values if llm_values is None else llm_values
    selected = llm_model or source.get("LLM_MODEL") or values.get("LLM_MODEL")
    provider = LLM_MODELS.get(selected)
    require(provider is not None, "INVALID_LLM_MODEL")
    declared = source.get("LLM_PROVIDER")
    require(bool(llm_model) or declared == provider, "INVALID_LLM_PROVIDER")
    key = source.get("OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY")
    if not key and (declared == provider or (llm_values is not None and not declared)):
        key = source.get("LLM_API_KEY")
    selected_image = image_model or values.get("IMAGE_MODEL")
    image_provider = "openai" if selected_image == "gpt-image-2" else "gemini"
    require(values.get("IMAGE_PROVIDER") == image_provider and selected_image in IMAGE_MODELS,
            "INVALID_IMAGE_CONFIGURATION")
    image_key = values.get("IMAGE_API_KEY")
    for secret in (key, image_key):
        require(isinstance(secret, str) and bool(secret) and secret.isascii()
                and not any(character.isspace() for character in secret), "INVALID_PROVIDER_KEY")
    return SimpleNamespace(llm_provider=provider, llm_model=selected, llm_api_key=key,
                           image_provider=image_provider, image_model=selected_image,
                           image_api_key=image_key, llm_timeout=90, image_timeout=90)


def load_runtime_config(args):
    """Only explicitly named files are loaded; dotenv content is never executed."""
    require(args.env_file.is_file(), "ENV_FILE_NOT_FOUND")
    if args.llm_env_file is not None:
        require(args.llm_env_file.is_file(), "LLM_ENV_FILE_NOT_FOUND")
    return runtime_config(
        dotenv_values(args.env_file, interpolate=False),
        llm_values=(dotenv_values(args.llm_env_file, interpolate=False)
                    if args.llm_env_file is not None else None),
        llm_model=args.llm_model, image_model=args.image_model,
    )


def quality_gate_environment(page_count, config):
    """Enable the same product gate in every new paid acceptance, before startup."""
    request_limits(page_count, True)
    require(config.llm_provider == "openai" and LLM_MODELS.get(config.llm_model) == "openai",
            "ILLUSTRATION_REVIEW_REQUIRES_VERIFIED_OPENAI_MODEL")
    return {"ILLUSTRATION_QUALITY_ENABLED": "true", "LIVE_ACCEPTANCE_PAGE_COUNT": str(page_count)}


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def write_guarded_entry(api, guard_module, *, capture_fictional_review=False):
    """A guard installation error must stop Python before importing the app."""
    require(guard_module in {"live_acceptance_guard", "photo_acceptance_guard"}, "INVALID_ACCEPTANCE_GUARD")
    require(type(capture_fictional_review) is bool,
            "INVALID_FICTIONAL_CAPTURE_OPTION")
    entry = api / "live_entry.py"
    entry.write_text(
        "import runpy, sys\nfrom " + guard_module + " import install\n"
        "install()\n"
        + ("from fictional_review_capture import install as install_capture\ninstall_capture()\n"
           if capture_fictional_review else "")
        + "module = sys.argv.pop(1)\nrunpy.run_module(module, run_name='__main__')\n"
    )
    return entry


def require_ignored_path(path):
    """Fail closed for tracked, unignored, or out-of-repository private material."""
    resolved = path.resolve()
    require(resolved.is_relative_to(ROOT.resolve()), "PRIVATE_PATH_OUTSIDE_REPOSITORY")
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--quiet", "--",
         str(resolved.relative_to(ROOT.resolve()))],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    require(result.returncode == 0, "PRIVATE_PATH_MUST_BE_GIT_IGNORED")


def load_reader_profile(path, age):
    """Read bounded private fields before paid work; errors never echo their values."""
    if path is None:
        return None
    require_ignored_path(path)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "INVALID_READER_PROFILE")
            result[key] = value
        return result

    try:
        require(not path.is_symlink(), "INVALID_READER_PROFILE_FILE")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            details = os.fstat(stream.fileno())
            require(stat.S_ISREG(details.st_mode) and stat.S_IMODE(details.st_mode) == 0o600,
                    "READER_PROFILE_REQUIRES_PRIVATE_FILE")
            require(not hasattr(os, "getuid") or details.st_uid == os.getuid(),
                    "READER_PROFILE_REQUIRES_PRIVATE_FILE")
            content = stream.read(4097)
        require(len(content) <= 4096, "INVALID_READER_PROFILE")
        profile = json.loads(content.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, ValueError):
        raise GateFailure("INVALID_READER_PROFILE_FILE") from None
    fields = {"protagonist_name", "character_gender", "character_age"}
    require(type(profile) is dict and "protagonist_name" in profile and set(profile) <= fields,
            "INVALID_READER_PROFILE")
    name = profile["protagonist_name"]
    require(type(name) is str and 1 <= len(name) <= 40 and name == name.strip()
            and not any(unicodedata.category(character).startswith("C")
                        or unicodedata.category(character) in {"Zl", "Zp"} for character in name),
            "INVALID_READER_PROFILE_NAME")
    if "character_gender" in profile:
        require(type(profile["character_gender"]) is str and profile["character_gender"] in {"boy", "girl"},
                "INVALID_READER_PROFILE_GENDER")
    if "character_age" in profile:
        actual_age = profile["character_age"]
        require(type(actual_age) is int and 3 <= actual_age <= 9, "INVALID_READER_PROFILE_AGE")
        require(age in {"3-5", "5-7", "7-9"}, "INVALID_READER_PROFILE_AGE_BAND")
        minimum, maximum = map(int, age.split("-"))
        require(minimum <= actual_age <= maximum, "READER_PROFILE_AGE_BAND_MISMATCH")
    return profile


def data_scope(reader_profile):
    fields = [field for field in ("protagonist_name", "character_gender", "character_age")
              if reader_profile is not None and field in reader_profile]
    return {"real_child_data": reader_profile is not None,
            "data_scope": {
                "user_supplied_child_name": reader_profile is not None,
                "personal_fields": fields,
                "age_source": "private_profile" if "character_age" in fields else "age_band_cli",
                "appearance": "fictional_fixture", "photos_used": False,
            }}


def unverified_candidate_readiness(http_status, payload):
    """Permit only a fresh isolated candidate's explicit provider probe gap."""
    services = payload.get("services", {})
    return (
        http_status == 503
        and services.get("provider_runtime") == "unverified"
        and all(services.get(name) == "healthy" for name in
                ("database", "redis", "job_monitor", "storage", "provider_keys"))
        and services.get("cost_budget") == "configured"
    )



def journey(base, directory, age, report, case=1, page_count=8, reader_profile=None, *, trial_owner=None):
    name = "하루" if reader_profile is None else reader_profile["protagonist_name"]
    owner = {"X-User-Key": trial_owner or str(uuid.uuid4())}
    with httpx.Client(base_url=base, timeout=90, trust_env=False) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, headers=owner, **kwargs)
            require(response.status_code == 200, f"{method} {path.split('?')[0]}: HTTP {response.status_code}")
            return response

        readiness = client.get("/health/ready")
        ready = readiness.json()
        report["readiness"] = ready
        report["readiness_http_status"] = readiness.status_code
        require(readiness.status_code == 200 or unverified_candidate_readiness(readiness.status_code, ready),
                "Disposable candidate dependencies are not ready")
        call("POST", "/v1/consent", json={"privacy": True, "photos": False, "data_processing": True})
        if trial_owner is not None:
            capabilities = call("GET", "/v1/config/capabilities").json()
            require(capabilities.get("free_first_book_trial") is True
                    and capabilities.get("generation_invitation_supported") is True
                    and capabilities.get("purchases_supported") is False, "TRIAL_CAPABILITIES_MISMATCH")
            require(call("GET", "/v1/credits/balance").json().get("credits") == 1,
                    "TRIAL_INITIAL_CREDIT_MISMATCH")
            report["trial_initial_credit"] = 1
        print("Creating character through the live adapter..." if reader_profile is not None else
              "Creating fictional character through the live adapter...", flush=True)
        traits = {
            1: "짧은 검은 단발머리, 노란 멜빵바지, 초록 장화, 호기심, 다정함",
            2: "짧은 곱슬머리, 둥근 빨간 안경, 파란 멜빵바지, 노란 운동화, 신중함, 용기",
            3: "검은 양갈래 머리, 초록 원피스, 흰 운동화, 호기심, 친구의 말을 잘 들음",
            4: "흰 털을 가진 작은 토끼, 파란 조끼, 빨간 목도리, 호기심, 친절함",
            5: "갈색 털을 가진 작은 곰, 노란 모자, 초록 조끼, 작은 둥근 귀, 인내심, 다정함",
        }[case]
        character_age = {"3-5": "4살", "5-7": "6살", "7-9": "8살"}[age]
        prefix = "실제 사람이 아닌 가상 캐릭터, "
        if reader_profile is not None:
            character_age = (f"{reader_profile['character_age']}살" if "character_age" in reader_profile
                             else f"{age}세")
            prefix = "실제 얼굴·머리·의상을 반영하지 않은 가상 외형, "
            if "character_gender" in reader_profile:
                prefix = {"boy": "남자아이, ", "girl": "여자아이, "}[reader_profile["character_gender"]] + prefix
        character = call("POST", "/v1/characters/from-text", data={
            "name": name, "age": character_age, "traits": prefix + traits,
            "style": "watercolor",
        }).json()
        save_json(directory / "character.json", character)
        topic = {"3-5": "하루가 정원에서 친구와 함께 씨앗에 물을 주는 이야기",
                 "5-7": "하루가 비 온 뒤 친구들과 작은 도서관의 젖은 책을 구하는 이야기",
                 "7-9": "하루가 친구들과 빗물을 모아 마을 정원을 살리는 방법을 찾는 이야기"}[age]
        if case != 1:
            topic = {
                2: "하루가 새로운 놀이에 도전하며 떨리는 마음을 말하고 어른과 함께 안전하게 연습하는 이야기",
                3: "하루가 친구와 같은 장난감을 가지고 놀고 싶어서 서로의 마음을 듣고 차례를 정하는 이야기",
                4: "토끼 하루가 친구들과 소풍 후 쓰레기를 정리하고 작은 숲을 깨끗하게 만드는 이야기",
                5: "곰 하루가 친구와 씨앗을 심고 매일 기다리며 작은 싹이 자라는 변화를 발견하는 이야기",
            }[case]
        if reader_profile is not None:
            last = ord(name[-1])
            particle = "이" if 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28 else "가"
            topic = topic.replace("하루가", name + particle)
        spec = {"topic": topic, "language": "ko", "target_age": age, "style": "watercolor",
                "page_count": page_count, "character_id": character["character_id"], "protagonist_name": name}
        started = time.monotonic()
        job_id = call("POST", "/v1/books", json=spec).json()["job_id"]
        if trial_owner is not None:
            with httpx.Client(base_url=base, timeout=15, trust_env=False) as reopened:
                active = reopened.get("/v1/books/active-generations", headers=owner)
                require(active.status_code == 200
                        and any(row["job_id"] == job_id for row in active.json()), "TRIAL_ACTIVE_JOB_NOT_FOUND")
            report["trial_reopened_job"] = "passed"
        stages = []
        while time.monotonic() - started < 660:
            job = call("GET", f"/v1/books/{job_id}").json()
            stage = {key: job.get(key) for key in ("status", "progress", "current_step")}
            if not stages or stage != stages[-1]["state"]:
                stages.append({"seconds": round(time.monotonic() - started, 2), "state": stage})
                print("Book progress: " + str(stage["progress"]) + "% / " + str(stage["status"]), flush=True)
            if job.get("status") in {"done", "failed"}:
                break
            time.sleep(2)
        report["generation_seconds"] = round(time.monotonic() - started, 2)
        report["stages"] = stages
        if job.get("status") != "done":
            report["job_error_code"] = job_error_code(job)
            raise GateFailure("Live book did not complete")
        book_id = job["result"]["book_id"]
        detail = call("GET", f"/v1/books/{book_id}/detail").json()
        report["book_id"] = book_id
        report["page_count"] = len(detail["pages"])
        report["learning_assets_available"] = detail.get("learning_assets") is not None
        require(report["page_count"] == page_count, "Unexpected page count")
        if age == "7-9" and page_count == 12:
            counts = [
                sum(any(character.isalnum() for character in word) for word in page["text"].split())
                for page in detail["pages"]
            ]
            report["korean_word_counts"] = counts
            long_pages = sum(count >= 40 for count in counts)
            report["korean_story_length"] = "target_met"
            if long_pages < 9:
                require(long_pages == 8 and any(38 <= count < 40 for count in counts),
                        "KOREAN_STORY_LENGTH_BELOW_MINIMUM")
                report["korean_story_length"] = "near_target"
        if trial_owner is not None:
            require(call("GET", "/v1/credits/balance").json().get("credits") == 0,
                    "TRIAL_FINAL_CREDIT_MISMATCH")
            require(any(row["book_id"] == book_id for row in call("GET", "/v1/library").json()["books"]),
                    "TRIAL_BOOK_NOT_IN_LIBRARY")
            final_ready = call("GET", "/health/ready").json()["services"]
            require(final_ready.get("provider_runtime") == "healthy", "TRIAL_PROVIDER_READINESS_UNVERIFIED")
            report.update(trial_final_credit=0, trial_book_in_library="passed")
            report["trial_provider_readiness"] = "healthy"
        report["generation_warnings"] = detail.get("generation_warnings", [])
        report["images"] = []
        for index, entry in enumerate([{"image_url": detail["cover_image_url"]}] + detail["pages"]):
            url = entry["image_url"]
            response = client.get(url)
            require(response.status_code == 200, "Private book image download failed")
            path = directory / f"page-{index:02d}.png"
            path.write_bytes(response.content)
            path.chmod(0o600)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                report["images"].append({"page": index, "width": image.width, "height": image.height})
            entry["image_url"] = path.name
        detail["cover_image_url"] = "page-00.png"
        # Private text and local asset names only; no signed URLs or auth keys.
        def scrub(value):
            if isinstance(value, dict):
                return {key: scrub(item) for key, item in value.items()
                        if not key.endswith("url") or key == "image_url" or key == "cover_image_url"}
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value
        save_json(directory / "book.json", scrub(detail))
        foreign = client.get(f"/v1/books/{book_id}/detail", headers={"X-User-Key": str(uuid.uuid4())})
        require(foreign.status_code in {403, 404}, "Cross-account ownership check failed")
        report["owner_media_and_foreign_denial"] = "passed"
        pdf = client.get(f"/v1/books/{book_id}/pdf", headers=owner)
        require(pdf.status_code == 402, "Free PDF entitlement gate changed")
        report["free_pdf_entitlement"] = "correctly blocked"
        # Private disposable fixture, removed before handoff. Used only by local app acceptance.
        save_json(directory / "private-fixture.json", {"base_url": base, "user_key": owner["X-User-Key"],
                                                     "book_id": book_id, "job_id": job_id})


def verify_final_narration(base, directory, report):
    """Synthesize the last page through the real invite-only audio route."""
    fixture = json.loads((directory / 'private-fixture.json').read_text())
    headers = {'X-User-Key': fixture['user_key']}
    route = f"/v1/books/{fixture['book_id']}/pages/12/audio"
    params = {'language': 'ko', 'voice': 'warm', 'style': 'animated'}
    with httpx.Client(base_url=base, timeout=125, trust_env=False) as client:
        cached = client.get(f'{route}/cached', headers=headers, params=params)
        require(cached.status_code == 200 and cached.json() == {'audio_url': None}, 'FINAL_AUDIO_NOT_FRESH')
        generated = client.get(route, headers=headers, params=params)
        require(generated.status_code == 200, f'FINAL_AUDIO_HTTP_{generated.status_code}')
        audio_url = generated.json()['audio_url']
        cached = client.get(f'{route}/cached', headers=headers, params=params)
        require(cached.status_code == 200 and cached.json().get('audio_url'), 'FINAL_AUDIO_NOT_CACHED')
        first = client.get(audio_url)
        second = client.get(cached.json()['audio_url'])
        require(first.status_code == second.status_code == 200 and first.content == second.content,
                'FINAL_AUDIO_STORAGE_MISMATCH')
    with wave.open(io.BytesIO(first.content), 'rb') as audio:
        require((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000),
                'FINAL_AUDIO_INVALID_FORMAT')
        duration = audio.getnframes() / audio.getframerate()
        require(duration >= 1 and len(audio.readframes(audio.getnframes())) == audio.getnframes() * 2,
                'FINAL_AUDIO_INCOMPLETE')
    (directory / 'page-12-narration.wav').write_bytes(first.content)
    report['final_narration'] = {'page': 12, 'voice': params['voice'], 'style': params['style'],
                                 'duration_seconds': duration, 'sha256': sha256(first.content).hexdigest(),
                                 'fresh_synthesis': True, 'cached_download_matches': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--llm-env-file", type=Path,
                        help="Separate LLM credential file; accepts OPENAI_API_KEY or LLM_API_KEY")
    parser.add_argument("--llm-model", choices=tuple(LLM_MODELS),
                        help="Explicit LLM comparison; never changes the active env file")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reader-profile-file", type=Path,
                        help="Private Git-ignored 0600 JSON: protagonist_name, optional character_gender/character_age")
    parser.add_argument("--retain-fictional-review-evidence", action="store_true",
                        help="Retain private QA inputs for a fully fictional 4- or 12-page case")
    parser.add_argument("--age", choices=("3-5", "5-7", "7-9"), default="5-7")
    parser.add_argument("--case", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--page-count", type=int, choices=ACCEPTANCE_PAGE_COUNTS, default=8)
    parser.add_argument("--image-model", choices=sorted(IMAGE_MODELS),
                        help="Explicit same-provider model comparison; never changes the env file")
    parser.add_argument("--image-concurrency", type=int, choices=(3, 4), default=3,
                        help="Compare parallel image requests in the disposable stack")
    parser.add_argument("--first-book-trial", action="store_true",
                        help="Use the invite-only free first-book policy for a fictional 12-page run")
    parser.add_argument("--verify-final-narration", action="store_true",
                        help="Also synthesize page 12 via OpenAI Realtime (up to three requests)")
    parser.add_argument("--hold-seconds", type=int, default=0, choices=range(0, 14401), metavar="0..14400")
    args = parser.parse_args()
    # Also covers child-process logs and dependency logs from the shared runner.
    previous_umask = os.umask(0o077)
    try:
        return run_acceptance(args)
    except GateFailure as error:
        print("Live acceptance failed: " + str(error), flush=True)
        return 1
    finally:
        os.umask(previous_umask)


def run_acceptance(args, *, profile=None):
    """Run the owned disposable stack; optional photo profile supplies its guarded journey."""
    image_concurrency = getattr(args, "image_concurrency", 3)
    require(type(image_concurrency) is int and image_concurrency in (3, 4)
            and (profile is None or image_concurrency == 3), "INVALID_IMAGE_CONCURRENCY")
    first_book_trial = getattr(args, "first_book_trial", False)
    final_narration = getattr(args, "verify_final_narration", False)
    require(not final_narration or (first_book_trial and args.age == "7-9"),
            "FINAL_NARRATION_REQUIRES_7_TO_9_FIRST_BOOK_TRIAL")
    require(not first_book_trial or (profile is None and args.reader_profile_file is None and args.page_count == 12),
            "TRIAL_REQUIRES_FICTIONAL_TWELVE_PAGE_RUN")
    require(profile is not None or args.page_count != 12 or args.reader_profile_file is None,
            "TWELVE_PAGE_RUN_REQUIRES_FICTIONAL_INPUT")
    directory = args.output_dir.resolve()
    require(directory.is_relative_to((ROOT / "docs/acceptance").resolve())
            and directory != (ROOT / "docs/acceptance").resolve() and not directory.exists(),
            "Output must be a new acceptance subdirectory")
    require_ignored_path(directory)
    for filename in ("character.json", "book.json", "result.json", "private-fixture.json",
                     "provider-usage.jsonl", "api.log", "worker.log", "dependencies.log",
                     "migrations.log", "cleanup.log", *(f"page-{index:02d}.png" for index in range(args.page_count + 1))):
        require_ignored_path(directory / filename)
    reader_profile = load_reader_profile(args.reader_profile_file, args.age)
    text_capture = bool(getattr(args, "retain_fictional_review_evidence", False))
    require(not text_capture or (profile is None and reader_profile is None and args.page_count in (4, 12)),
            "REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN")
    config = profile.config if profile is not None else load_runtime_config(args)
    require(not final_narration or config.llm_provider == "openai", "FINAL_NARRATION_REQUIRES_OPENAI_KEY")
    if final_narration:
        require_ignored_path(directory / 'page-12-narration.wav')
    quality_environment = profile.environment if profile is not None else quality_gate_environment(args.page_count, config)
    directory.mkdir(parents=True, mode=0o700)
    capture_fictional = text_capture or bool(profile is not None and getattr(profile, "retain_fictional_review_evidence", False))
    if capture_fictional:
        require(text_capture or (profile.report_fields.get("source_classification") == "fictional_image"
                and profile.report_fields.get("real_child_data") is False),
                "REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN")
        evidence = directory / "fictional-review-evidence"
        require_ignored_path(evidence)
        evidence.mkdir(mode=0o700)
        quality_environment = {**quality_environment,
                               "LIVE_FICTIONAL_REVIEW_CAPTURE": "true",
                               "LIVE_ACCEPTANCE_SOURCE_CLASSIFICATION": "fictional_image",
                               "LIVE_FICTIONAL_REVIEW_DIRECTORY": str(evidence),
                               "LIVE_ACCEPTANCE_REPOSITORY_ROOT": str(ROOT.resolve())}
    journal = directory / "provider-usage.jsonl"
    journal.touch(mode=0o600)
    env = clean_environment()
    report = {"status": "failed", "started_at": datetime.now(timezone.utc).isoformat(),
              "age": args.age, "case": args.case, "requested_pages": args.page_count,
              "real_ai": True, **data_scope(reader_profile),
              "request_limits": profile.request_limits if profile is not None else request_limits(args.page_count, True),
              "illustration_quality_enabled": True, "quality_review_max_calls": 4,
              "image_max_concurrent": image_concurrency,
              "rate_limit_config": {"mutations": 10, "reads": 120, "window_seconds": 60},
              "provider_journal_version": JOURNAL_VERSION,
              "llm_output_token_limit": LLM_TOKEN_LIMITS[config.llm_provider],
              "providers": {"llm": config.llm_provider, "image": config.image_provider},
              "models": {"llm": config.llm_model, "image": config.image_model}}
    if profile is not None:
        report.update(profile.report_fields)
    trial_environment = first_book_trial_environment() if first_book_trial else {}
    trial_owner = trial_environment.pop("RUNTIME_TRIAL_OWNER", None)
    if first_book_trial:
        report["first_book_trial"] = True
    project = "storybook-live-" + uuid.uuid4().hex[:12]
    compose = ["docker", "compose", "--project-name", project, "--env-file", os.devnull,
               "-f", str(ROOT / "infra/docker-compose.e2e.yml")]
    processes, handles = [], []
    started = False

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        host = env.get("DOCKER_HOST") if not env.get("DOCKER_CONTEXT") else None
        host = host or run(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], env=env).strip()
        require(host.startswith(("unix://", "npipe://")), "Only local Docker is permitted")
        for image in IMAGES:
            run(["docker", "image", "inspect", image], env=env)
        with tempfile.TemporaryDirectory(prefix="storybook-live-source-") as temporary:
            api = Path(temporary) / "api"
            api.mkdir()
            for name in ("src", "alembic", "assets"):
                shutil.copytree(ROOT / "apps/api" / name, api / name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*"))
            shutil.copy2(ROOT / "apps/api/alembic.ini", api / "alembic.ini")
            shutil.copy2(ROOT / "scripts/live_acceptance_guard.py", api / "live_acceptance_guard.py")
            guard_module = "live_acceptance_guard"
            if profile is not None:
                guard_module = profile.guard_module
                require(guard_module == "photo_acceptance_guard", "INVALID_ACCEPTANCE_GUARD")
                shutil.copy2(ROOT / "scripts/photo_acceptance_guard.py", api / "photo_acceptance_guard.py")
            if capture_fictional:
                shutil.copy2(ROOT / "scripts/fictional_review_capture.py", api / "fictional_review_capture.py")
            # Python ignores sitecustomize exceptions and continues startup.
            # A normal entrypoint makes guard failure fatal before any app import.
            entry = write_guarded_entry(api, guard_module, capture_fictional_review=capture_fictional)
            started = True
            run(compose + ["up", "-d", "--pull", "never", "--wait", "--wait-timeout", "90"],
                env=env, log=directory / "dependencies.log")
            pg, redis, s3 = [port_for(compose, service, port, env) for service, port in
                             (("postgres", 5432), ("redis", 6379), ("minio", 9000))]
            runtime = dict(env, PYTHONPATH=str(api), TESTING="false", USE_CELERY="true",
                DATABASE_URL=f"postgresql+asyncpg://runtime_test:disposable-runtime-password@127.0.0.1:{pg}/runtime_test",
                REDIS_URL=f"redis://127.0.0.1:{redis}/0", CELERY_BROKER_URL=f"redis://127.0.0.1:{redis}/1",
                CELERY_RESULT_BACKEND=f"redis://127.0.0.1:{redis}/2",
                S3_ENDPOINT=f"http://127.0.0.1:{s3}", S3_DOWNLOAD_ENDPOINT=f"http://127.0.0.1:{s3}",
                S3_PUBLIC_URL=f"http://127.0.0.1:{s3}/runtime-test", S3_BUCKET="runtime-test",
                S3_ACCESS_KEY="runtime_test", S3_SECRET_KEY="disposable-runtime-password",
                TTS_PROVIDER="mock", STT_PROVIDER="mock", AUDIO_FEATURE_ENABLED="false",
                POD_ORDERING_ENABLED="false", PURCHASES_ENABLED="false", IAP_VERIFICATION_MODE="strict",
                RATE_LIMIT_REQUESTS="10", RATE_LIMIT_READ_REQUESTS="120", RATE_LIMIT_WINDOW="60",
                DAILY_GENERATION_BUDGET="2", LLM_TIMEOUT="90",
                IMAGE_MAX_RETRIES="1", IMAGE_MAX_CONCURRENT=str(image_concurrency),
                LIVE_ACCEPTANCE_JOURNAL=str(journal),
                OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")
            runtime.update(quality_environment)
            runtime.update(trial_environment)
            if final_narration:
                runtime.update(TTS_PROVIDER="openai_realtime", AUDIO_FEATURE_ENABLED="true",
                               AUDIO_NARRATION_ONLY_ENABLED="true", OPENAI_TTS_API_KEY=config.llm_api_key,
                               DAILY_GENERATION_BUDGET="5")
            runtime.update({key.upper(): str(value) for key, value in vars(config).items()
                            if key not in {"llm_timeout", "image_timeout"}})
            run([sys.executable, str(entry), "alembic", "upgrade", "head"], env=runtime,
                cwd=api, log=directory / "migrations.log")
            port = free_port()
            for name, command in (("worker", [sys.executable, str(entry), "celery", "-A", "src.worker", "worker",
                                              "--loglevel=warning", "--concurrency=1", "--pool=solo"]),
                                  ("api", [sys.executable, str(entry), "uvicorn", "src.main:app", "--host", "127.0.0.1",
                                           "--port", str(port), "--no-access-log"])):
                handle = (directory / f"{name}.log").open("w")
                handles.append(handle)
                processes.append(subprocess.Popen(command, env=runtime, cwd=api, stdout=handle,
                                                   stderr=subprocess.STDOUT, start_new_session=True))
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                require(all(process.poll() is None for process in processes), "Disposable process stopped")
                try:
                    if httpx.get(base + "/health/live", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            if profile is None:
                journey(base, directory, args.age, report, args.case, args.page_count, reader_profile,
                        trial_owner=trial_owner)
                if final_narration:
                    verify_final_narration(base, directory, report)
            else:
                profile.journey(base, directory, report, runtime)
            report["status"] = "passed"
            save_json(directory / "result.json", report)
            print(f"Book completed. Local app fixture ready in {directory}", flush=True)
            deadline = time.monotonic() + args.hold_seconds
            while time.monotonic() < deadline and not (directory / "STOP").exists():
                time.sleep(1)
    except Exception as error:
        report["failure"] = str(error) if isinstance(error, GateFailure) else type(error).__name__
        print("Live acceptance failed: " + report["failure"], flush=True)
    finally:
        for process in reversed(processes):
            stop_process_group(process)
        for handle in handles:
            handle.close()
        if started:
            try:
                run(compose + ["down", "--volumes", "--remove-orphans"], env=env,
                    timeout=90, log=directory / "cleanup.log")
                report["cleanup"] = "completed"
            except Exception:
                report.update(status="failed", cleanup="failed", compose_project=project)
        (directory / "private-fixture.json").unlink(missing_ok=True)
        save_json(directory / "result.json", report)
        print("Live acceptance: " + report["status"], flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
