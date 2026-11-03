"""Bound incoming HTTP bodies before request parsers spool untrusted uploads.

This middleware never buffers a request. It stops forwarding ASGI chunks once
the byte limit is crossed. The multipart-specific exception also makes
Starlette close any files it already spooled before the limit was crossed.
"""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


# Existing pronunciation and family-voice routes each permit a 15 MiB file;
# allow a further 2 MiB for the multipart envelope and form fields.
MAX_REQUEST_BODY_BYTES = 17 * 1024 * 1024


class _RequestBodyTooLarge(MultiPartException):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_body_bytes=MAX_REQUEST_BODY_BYTES):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject():
            message = "요청 본문이 너무 큽니다."
            content = {"detail": message, "error": {"code": "REQUEST_TOO_LARGE", "message": message}}
            request_id = scope.get("state", {}).get("request_id")
            if request_id:
                content["request_id"] = request_id
            await JSONResponse(content, status_code=413)(scope, receive, send)

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    if int(value) > self.max_body_bytes:
                        await reject()
                        return
                except ValueError:
                    # The server validates malformed framing; still count actual
                    # received bytes if the ASGI server passes a bad value on.
                    pass

        received = 0
        exceeded = False
        response_started = False
        rejected = False

        async def limited_receive():
            nonlocal received, exceeded
            event = await receive()
            if event["type"] == "http.request":
                received += len(event.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    # MultiPartParser closes already-open spooled files only for
                    # MultiPartException; FastAPI may translate it into 400.
                    raise _RequestBodyTooLarge("Request body exceeds configured limit")
            return event

        async def limited_send(event):
            nonlocal response_started, rejected
            if exceeded and not response_started:
                await reject()
                response_started = True
                rejected = True
            elif exceeded and not rejected:
                # A streaming app may already have committed its status before
                # consuming the request. Terminate rather than falsely finish a
                # successful response or emit an invalid second status.
                raise _RequestBodyTooLarge("Request body exceeds configured limit")
            if rejected:
                return
            if event["type"] == "http.response.start":
                response_started = True
            await send(event)

        try:
            await self.app(scope, limited_receive, limited_send)
        except _RequestBodyTooLarge:
            if not response_started:
                await reject()
            elif not rejected:
                # The response was already committed by a streaming app. It is
                # too late to send a second status; let the server abort it.
                raise
        except Exception:
            if exceeded and not response_started:
                # A downstream parser can translate the limit signal into a
                # different exception instead of producing a response.
                await reject()
            elif not (exceeded and rejected):
                raise
