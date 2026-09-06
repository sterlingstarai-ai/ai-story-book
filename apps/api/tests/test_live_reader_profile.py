"""Private reader input and outputs use only fictional sentinel names in tests."""

from io import BytesIO
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
from PIL import Image
import pytest


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import run_live_book_acceptance as book
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text("private/\ndocs/acceptance/*\n")
    (root / "private").mkdir(mode=0o700)
    monkeypatch.setattr(book, "ROOT", root)
    return book, root


def write_profile(root, value):
    path = root / "private/reader.json"
    path.write_text(json.dumps(value, ensure_ascii=False))
    path.chmod(0o600)
    return path


def test_profile_is_bounded_and_summary_marks_child_data_without_copying_name(harness):
    book, root = harness
    name = "가" * 40
    path = write_profile(root, {"protagonist_name": name})
    content = path.read_bytes()
    assert book.load_reader_profile(path, "7-9") == {"protagonist_name": name}
    assert book.load_reader_profile(None, "7-9") is None
    assert path.read_bytes() == content
    summary = book.data_scope({"protagonist_name": name})
    assert summary["real_child_data"] is True
    assert summary["data_scope"] == {
        "user_supplied_child_name": True, "personal_fields": ["protagonist_name"],
        "age_source": "age_band_cli", "appearance": "fictional_fixture", "photos_used": False,
    }
    assert name not in json.dumps(summary, ensure_ascii=False)
    assert book.data_scope(None)["real_child_data"] is False
    assert book.data_scope(None)["data_scope"]["personal_fields"] == []


def test_optional_gender_and_age_are_validated_and_reported_as_used_fields(harness):
    book, root = harness
    profile = {"protagonist_name": "테스트별", "character_gender": "girl", "character_age": 5}
    path = write_profile(root, profile)
    assert book.load_reader_profile(path, "3-5") == profile
    scope = book.data_scope(profile)["data_scope"]
    assert scope["personal_fields"] == ["protagonist_name", "character_gender", "character_age"]
    assert scope["age_source"] == "private_profile"
    assert "테스트별" not in json.dumps(scope, ensure_ascii=False)
    with pytest.raises(book.GateFailure, match="AGE_BAND_MISMATCH"):
        book.load_reader_profile(path, "7-9")


@pytest.mark.parametrize("payload", [
    {"protagonist_name": ""}, {"protagonist_name": "  "}, {"protagonist_name": True},
    {"protagonist_name": 123}, {"protagonist_name": "가" * 41},
    {"protagonist_name": "테스트\n별"}, {"protagonist_name": "테스트\u2028별"},
    {"protagonist_name": "테스트별", "unknown_private_field": "private-value"},
    {"protagonist_name": "테스트별", "character_gender": "unknown"},
    {"protagonist_name": "테스트별", "character_gender": ["girl"]},
    {"protagonist_name": "테스트별", "character_age": True},
    {"protagonist_name": "테스트별", "character_age": 10},
    {"protagonist_name": "테스트별", "character_age": "5"},
    ["private-value"], None,
])
def test_invalid_profile_fails_before_configuration_or_paid_work(harness, monkeypatch, payload):
    book, root = harness
    path = write_profile(root, payload)
    monkeypatch.setattr(book, "load_runtime_config", lambda _args: pytest.fail("No paid setup allowed"))
    output = root / "docs/acceptance/reader-sample"
    with pytest.raises(book.GateFailure) as caught:
        book.run_acceptance(SimpleNamespace(output_dir=output, reader_profile_file=path, age="7-9", page_count=8))
    assert str(caught.value).startswith("INVALID_READER_PROFILE")
    assert "private-value" not in str(caught.value)
    assert "unknown_private_field" not in str(caught.value)
    assert not output.exists()


@pytest.mark.parametrize("failure", ["duplicate", "oversize", "unignored", "tracked", "public",
                                      "symlink", "missing", "outside", "fifo"])
def test_profile_file_privacy_and_json_fail_closed(harness, tmp_path, failure):
    book, root = harness
    path = write_profile(root, {"protagonist_name": "테스트별"})
    if failure == "duplicate":
        path.write_text('{"protagonist_name":"private-value","protagonist_name":"private-value"}')
    elif failure == "oversize":
        path.write_text(" " * 4097)
    elif failure == "unignored":
        path = path.rename(root / "public.json")
    elif failure == "tracked":
        subprocess.run(["git", "-C", str(root), "add", "-f", str(path)], check=True, capture_output=True)
    elif failure == "public":
        path.chmod(0o644)
    elif failure == "symlink":
        link = root / "private/link.json"
        link.symlink_to(path)
        path = link
    elif failure == "missing":
        path.unlink()
    elif failure == "outside":
        path = path.rename(tmp_path / "outside.json")
    elif failure == "fifo":
        path.unlink()
        os.mkfifo(path, mode=0o600)
    with pytest.raises(book.GateFailure) as caught:
        book.load_reader_profile(path, "7-9")
    assert "private-value" not in str(caught.value)
    assert str(path) not in str(caught.value)


def test_unignored_output_is_rejected_before_paid_work(harness, monkeypatch):
    book, root = harness
    (root / ".gitignore").write_text("private/\n")
    monkeypatch.setattr(book, "load_runtime_config", lambda _args: pytest.fail("No paid setup allowed"))
    with pytest.raises(book.GateFailure, match="GIT_IGNORED"):
        book.run_acceptance(SimpleNamespace(output_dir=root / "docs/acceptance/public",
                                            reader_profile_file=None, age="7-9", page_count=8))


@pytest.mark.parametrize("reader_profile", [None, {"protagonist_name": "테스트별"},
                                          {"protagonist_name": "테스트별", "character_gender": "girl",
                                           "character_age": 5}])
def test_journey_consistent_name_fictional_appearance_and_private_artifacts(
    harness, monkeypatch, capsys, reader_profile,
):
    book, root = harness
    directory = root / "private/sample"
    directory.mkdir(mode=0o700)
    requests = []
    owner = None
    name = "하루" if reader_profile is None else reader_profile["protagonist_name"]
    age = "3-5" if reader_profile is not None and "character_age" in reader_profile else "7-9"
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")

    def respond(request):
        nonlocal owner
        requests.append(request)
        path = request.url.path
        if path == "/health/ready":
            owner = request.headers["X-User-Key"]
            return httpx.Response(200, json={"ready": True})
        if path == "/v1/consent":
            return httpx.Response(200, json={})
        if path == "/v1/characters/from-text":
            return httpx.Response(200, json={"character_id": "synthetic-character", "name": name})
        if path == "/v1/books":
            return httpx.Response(200, json={"job_id": "synthetic-job"})
        if path == "/v1/books/synthetic-job":
            return httpx.Response(200, json={"status": "done", "progress": 100, "current_step": "done",
                                            "result": {"book_id": "synthetic-book"}})
        if path == "/v1/books/synthetic-book/detail":
            if request.headers["X-User-Key"] != owner:
                return httpx.Response(403)
            return httpx.Response(200, json={
                "title": name, "cover_image_url": "http://assets.invalid/0",
                "pages": [{"text": name, "image_url": f"http://assets.invalid/{index}"}
                          for index in range(1, 9)],
            })
        if path == "/v1/books/synthetic-book/pdf":
            return httpx.Response(402)
        if request.url.host == "assets.invalid":
            return httpx.Response(200, content=buffer.getvalue())
        pytest.fail("Unexpected request in offline journey")

    original_client = httpx.Client
    monkeypatch.setattr(book.httpx, "Client", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond)))
    report = book.data_scope(reader_profile)
    book.journey("http://api.invalid", directory, age, report, page_count=8, reader_profile=reader_profile)
    assert report["stages"][0]["state"] == {"status": "done", "progress": 100, "current_step": "done"}
    character = parse_qs(next(request.content.decode() for request in requests
                             if request.url.path == "/v1/characters/from-text"))
    spec = json.loads(next(request.content for request in requests if request.url.path == "/v1/books"))
    assert character["name"] == [name]
    assert character["age"] == ["8살" if reader_profile is None else
                                "5살" if "character_age" in reader_profile else "7-9세"]
    assert character["traits"][0].endswith("짧은 검은 단발머리, 노란 멜빵바지, 초록 장화, 호기심, 다정함")
    assert spec["protagonist_name"] == name
    assert spec["target_age"] == age and spec["page_count"] == 8
    assert spec["topic"].startswith("하루가" if reader_profile is None else "테스트별이")
    if reader_profile is not None:
        assert "실제 얼굴·머리·의상을 반영하지 않은 가상 외형" in character["traits"][0]
        if "character_gender" in reader_profile:
            assert character["traits"][0].startswith("여자아이, ")
        assert "하루" not in spec["topic"]
        assert name not in capsys.readouterr().out
        assert name not in json.dumps(report, ensure_ascii=False)
    assert len(list(directory.glob("page-*.png"))) == 9
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())
    saved = (directory / "book.json").read_text()
    assert name in saved and "assets.invalid" not in saved and owner not in saved


def test_main_restricts_log_permissions_and_restores_umask_after_failure(harness, monkeypatch):
    book, root = harness
    monkeypatch.setattr(book.sys, "argv", ["run_live_book_acceptance.py", "--live", "--env-file",
                                           "unused.env", "--output-dir", str(root / "private/output")])
    original_umask = os.umask(0o022)
    try:
        def simulate_failure(args):
            args.output_dir.mkdir()
            (args.output_dir / "api.log").write_text("private-log-sentinel")
            raise book.GateFailure("TEST_FAILURE")
        monkeypatch.setattr(book, "run_acceptance", simulate_failure)
        assert book.main() == 1
        assert stat.S_IMODE((root / "private/output").stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "private/output/api.log").stat().st_mode) == 0o600
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(original_umask)


@pytest.fixture
def matrix_harness(harness, monkeypatch):
    book, root = harness
    import run_live_quality_matrix as matrix
    monkeypatch.setattr(matrix, "ROOT", root)
    monkeypatch.setattr(matrix, "load_runtime_config", lambda _args: SimpleNamespace(
        llm_provider="openai", llm_model="gpt-5.6-sol",
        image_provider="gemini", image_model="gemini-3-pro-image"))
    monkeypatch.setattr(matrix, "costs", lambda _output: (0.001, 0.001))
    monkeypatch.setattr(matrix.sys, "argv", ["run_live_quality_matrix.py", "--live",
        "--env-file", str(root / "unused.env"), "--reader-profile-file", str(root / "private/reader.json"),
        "--output-dir", str(root / "docs/acceptance/matrix")])
    return book, matrix, root


def test_matrix_forwards_private_profile_to_every_age_without_name_in_logs_or_summary(
    matrix_harness, monkeypatch, capsys,
):
    _, matrix, root = matrix_harness
    name = "테스트별"
    path = write_profile(root, {"protagonist_name": name, "character_gender": "girl"})
    commands = []

    def mock_child(command, **kwargs):
        commands.append(command)
        assert command[command.index("--reader-profile-file") + 1] == str(path.resolve())
        assert name not in " ".join(command)
        assert name not in json.dumps(kwargs["env"])
        kwargs["stdout"].write("Offline child completed\n")
        return SimpleNamespace(returncode=0)

    # Keep the profile loader's real local git checks; intercept only paid child execution.
    monkeypatch.setattr(matrix, "subprocess", SimpleNamespace(run=mock_child, STDOUT=subprocess.STDOUT))
    assert matrix.main() == 0
    assert len(commands) == 15
    assert {(command[command.index("--age") + 1], command[command.index("--case") + 1])
            for command in commands} == {(age, str(case)) for age in ("3-5", "5-7", "7-9")
                                        for case in range(1, 6)}
    directory = root / "docs/acceptance/matrix"
    result = json.loads((directory / "matrix.json").read_text())
    assert result["status"] == "passed" and len(result["completed"]) == 15
    assert result["real_child_data"] is True
    assert result["data_scope"]["personal_fields"] == ["protagonist_name", "character_gender"]
    assert result["data_scope"]["photos_used"] is False
    assert result["illustration_quality_enabled"] is True
    assert result["request_limits_per_book"] == {"llm": 16, "image": 7}
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert len(list(directory.glob("*.log"))) == 15
    for artifact in directory.iterdir():
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
        assert name not in artifact.read_text()
    assert name not in capsys.readouterr().out


def test_matrix_rejects_exact_age_before_any_child_execution(matrix_harness, monkeypatch):
    book, matrix, root = matrix_harness
    write_profile(root, {"protagonist_name": "테스트별", "character_age": 5})
    monkeypatch.setattr(matrix, "ThreadPoolExecutor", lambda **_kwargs: pytest.fail("No paid child allowed"))
    monkeypatch.setattr(matrix, "subprocess", SimpleNamespace(
        run=lambda *_args, **_kwargs: pytest.fail("No paid child allowed"), STDOUT=subprocess.STDOUT))
    with pytest.raises(book.GateFailure, match="AGE_BAND"):
        matrix.main()
    assert not (root / "docs/acceptance/matrix").exists()


def test_matrix_child_failure_never_copies_private_exception_into_summary(
    matrix_harness, monkeypatch, capsys,
):
    _, matrix, root = matrix_harness
    name = "테스트별"
    write_profile(root, {"protagonist_name": name})
    commands = []

    def fail_child(command, **_kwargs):
        commands.append(command)
        raise RuntimeError(name + " private child failure")

    monkeypatch.setattr(matrix, "subprocess", SimpleNamespace(run=fail_child, STDOUT=subprocess.STDOUT))
    assert matrix.main() == 1
    assert len(commands) == 2  # Initial in-flight pair only; no later paid work is scheduled.
    directory = root / "docs/acceptance/matrix"
    result = json.loads((directory / "matrix.json").read_text())
    assert result["unstarted_cases"] == 13 and result["status"] == "failed"
    assert all(entry["failure"] == "RuntimeError" for entry in result["completed"])
    assert name not in capsys.readouterr().out
    for artifact in directory.iterdir():
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
        assert name not in artifact.read_text()
