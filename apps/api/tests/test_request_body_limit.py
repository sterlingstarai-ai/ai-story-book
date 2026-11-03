"""ASGI request-size limit: incremental reads and multipart cleanup."""

import asyncio
from pathlib import Path
import re
import socket
from tempfile import SpooledTemporaryFile

import pytest
from fastapi import FastAPI, File, UploadFile
import httpx
from starlette import formparsers
import uvicorn

from src.core.request_body_limit import RequestBodyLimitMiddleware


def make_app(limit):
    app = FastAPI()
    app.state.handled = 0

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        app.state.handled += 1
        return {"size": len(await file.read())}

    @app.post("/json")
    async def receive_json(payload: dict):
        app.state.handled += 1
        return payload

    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=limit)
    return app


async def asgi_request(app, path, chunks, *, content_type, content_length=None, expect_abort=False):
    headers = [(b"content-type", content_type.encode())]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": b"", "headers": headers,
             "client": ("127.0.0.1", 1234), "server": ("test", 80), "root_path": ""}
    chunks = list(chunks)
    events = []
    receive_count = 0

    async def receive():
        nonlocal receive_count
        receive_count += 1
        if chunks:
            chunk = chunks.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}
        return {"type": "http.disconnect"}

    async def send(event):
        events.append(event)

    try:
        await app(scope, receive, send)
    except formparsers.MultiPartException:
        if not expect_abort:
            raise
    starts = [event for event in events if event["type"] == "http.response.start"]
    assert len(starts) == 1, events
    return starts[0]["status"], events, receive_count


def multipart_parts(data):
    prefix = (b"--test-boundary\r\nContent-Disposition: form-data; "
              b'name="file"; filename="sample.wav"\r\n'
              b"Content-Type: audio/wav\r\n\r\n")
    return prefix, data, b"\r\n--test-boundary--\r\n"


@pytest.mark.asyncio
async def test_declared_oversize_rejected_without_consuming_body():
    app = make_app(16)
    status, _, calls = await asgi_request(app, "/json", [b"not read"],
                                          content_type="application/json", content_length=17)
    assert (status, calls, app.state.handled) == (413, 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, 2])
async def test_unknown_or_misleading_length_is_counted_incrementally(declared):
    app = make_app(16)
    status, events, calls = await asgi_request(app, "/json", [b'{"x":"', b"a" * 12, b'"}'],
                                                content_type="application/json", content_length=declared)
    assert status == 413
    assert app.state.handled == 0
    assert calls == 2  # the third chunk is never handed to the parser
    assert sum(e["type"] == "http.response.body" and not e.get("more_body", False)
               for e in events) == 1


@pytest.mark.asyncio
async def test_oversized_chunked_multipart_closes_spooled_file(monkeypatch):
    made = []

    def tracked_file(*_args, **_kwargs):
        file = SpooledTemporaryFile(max_size=16)
        made.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_file)
    prefix, data, ending = multipart_parts(b"x" * 64)
    app = make_app(len(prefix) + len(data) + 3)
    status, _, calls = await asgi_request(
        app, "/upload", [prefix, data, b"x" * 8, ending],
        content_type="multipart/form-data; boundary=test-boundary")
    assert status == 413
    assert calls == 3 and app.state.handled == 0
    assert len(made) == 1 and made[0]._rolled and made[0].closed


@pytest.mark.asyncio
async def test_15_mib_audio_and_multipart_overhead_are_allowed():
    app = make_app(17 * 1024 * 1024)
    prefix, data, ending = multipart_parts(b"a" * (15 * 1024 * 1024))
    chunks = [prefix, *(data[i:i + 65536] for i in range(0, len(data), 65536)), ending]
    status, _, _ = await asgi_request(
        app, "/upload", chunks, content_type="multipart/form-data; boundary=test-boundary")
    assert status == 200 and app.state.handled == 1


@pytest.mark.asyncio
async def test_response_started_before_read_never_receives_a_second_start():
    async def early_response(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        try:
            await receive()
        except Exception:
            pass
        await send({"type": "http.response.body", "body": b"ok"})

    app = RequestBodyLimitMiddleware(early_response, max_body_bytes=4)
    status, events, _ = await asgi_request(app, "/", [b"oversized"],
                                            content_type="application/octet-stream", expect_abort=True)
    assert status == 200
    assert sum(event["type"] == "http.response.start" for event in events) == 1
    assert not any(event["type"] == "http.response.body" for event in events)


@pytest.mark.asyncio
async def test_incremental_request_and_streamed_response_preserve_chunks():
    seen = []

    async def stream_app(scope, receive, send):
        while True:
            event = await receive()
            seen.append(event["body"])
            if not event.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await send({"type": "http.response.body", "body": b"second", "more_body": False})

    app = RequestBodyLimitMiddleware(stream_app, max_body_bytes=6)
    status, events, calls = await asgi_request(app, "/", [b"ab", b"cd", b"ef"],
                                                content_type="application/octet-stream")
    assert status == 200 and calls == 3 and seen == [b"ab", b"cd", b"ef"]
    assert [event["body"] for event in events if event["type"] == "http.response.body"] == [b"first", b"second"]


@pytest.mark.asyncio
async def test_translated_parser_error_cannot_turn_limit_rejection_into_500():
    async def translating_app(scope, receive, send):
        try:
            await receive()
        except formparsers.MultiPartException as exc:
            raise RuntimeError("parser translated error") from exc

    app = RequestBodyLimitMiddleware(translating_app, max_body_bytes=4)
    status, events, _ = await asgi_request(app, "/", [b"oversized"],
                                           content_type="application/octet-stream")
    assert status == 413
    assert sum(event["type"] == "http.response.start" for event in events) == 1


@pytest.mark.asyncio
async def test_unrelated_downstream_error_is_not_hidden():
    async def broken_app(scope, receive, send):
        raise RuntimeError("unrelated failure")

    app = RequestBodyLimitMiddleware(broken_app, max_body_bytes=4)
    with pytest.raises(RuntimeError, match="unrelated failure"):
        await asgi_request(app, "/", [b"ok"], content_type="application/octet-stream")


@pytest.mark.asyncio
async def test_real_api_middleware_returns_413_for_chunked_photo(client, headers):
    prefix = (b"--test-boundary\r\nContent-Disposition: form-data; "
              b'name="photo"; filename="child.png"\r\n'
              b"Content-Type: image/png\r\n\r\n")
    sent = []

    async def stream():
        yield prefix
        for index in range(18):
            sent.append(index)
            yield b"x" * (1024 * 1024)
        yield b"\r\n--test-boundary--\r\n"

    response = await client.post(
        "/v1/characters/from-photo",
        content=stream(),
        headers={**headers, "content-type": "multipart/form-data; boundary=test-boundary",
                 "X-Request-ID": "body-limit-regression"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert response.headers["x-request-id"] == "body-limit-regression"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert len(sent) == 17


def test_nginx_limit_matches_api_and_exceeds_audio_file_limit():
    repo = Path(__file__).resolve().parents[3]
    config = (repo / "infra/nginx/nginx.conf").read_text()
    match = re.search(r"client_max_body_size\s+(\d+)M\s*;", config)
    assert match
    assert int(match.group(1)) * 1024 * 1024 == 17 * 1024 * 1024


@pytest.mark.asyncio
async def test_real_uvicorn_receives_15_mib_and_rejects_chunked_oversize():
    app = make_app(17 * 1024 * 1024)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(300):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert server.started, "owned Uvicorn server failed to start"
        prefix, _, ending = multipart_parts(b"")

        async def stream(mib):
            yield prefix
            for _ in range(mib):
                yield b"a" * (1024 * 1024)
            yield ending

        async with httpx.AsyncClient(timeout=20) as client:
            headers = {"content-type": "multipart/form-data; boundary=test-boundary"}
            allowed = await client.post(f"http://127.0.0.1:{port}/upload", headers=headers, content=stream(15))
            assert allowed.status_code == 200 and allowed.json()["size"] == 15 * 1024 * 1024
            rejected = await client.post(f"http://127.0.0.1:{port}/upload", headers=headers, content=stream(18))
            assert rejected.status_code == 413 and app.state.handled == 1
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        sock.close()
