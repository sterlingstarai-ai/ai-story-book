"""Reference fetch failures never journal private paths, signatures, or error text."""

from unittest.mock import Mock

import httpx
import pytest

from src.services import image


@pytest.mark.asyncio
async def test_ssrf_rejection_omits_private_reference_url_without_fetching(monkeypatch):
    url = "http://169.254.169.254/private-child-path?X-Amz-Signature=private-signature"
    logger = Mock()
    monkeypatch.setattr(image, "logger", logger)

    def forbidden_client(*args, **kwargs):
        pytest.fail("The real SSRF guard must reject before opening an HTTP client")

    monkeypatch.setattr(image.httpx, "AsyncClient", forbidden_client)
    assert await image._fetch_image_as_base64(url) is None
    logger.warning.assert_called_once_with("reference image URL blocked by SSRF protection")
    recorded = str(logger.mock_calls)
    assert "private-child-path" not in recorded
    assert "private-signature" not in recorded
    assert url not in recorded


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class", [httpx.ReadTimeout, RuntimeError])
async def test_fetch_failure_logs_only_exception_type_and_preserves_timeout(
    monkeypatch, error_class,
):
    url = "https://replicate.delivery/private-child-path?X-Amz-Signature=private-signature"
    detail = f"private-exception-body while requesting {url}"
    logger = Mock()
    monkeypatch.setattr(image, "logger", logger)
    requests = []

    def fail_fetch(request):
        requests.append(request)
        raise error_class(detail)

    real_client = httpx.AsyncClient

    def client(*, timeout):
        assert timeout == 30
        return real_client(timeout=timeout, transport=httpx.MockTransport(fail_fetch))

    monkeypatch.setattr(image.httpx, "AsyncClient", client)
    assert await image._fetch_image_as_base64(url) is None
    assert len(requests) == 1
    assert str(requests[0].url) == url
    logger.warning.assert_called_once_with(
        "reference image fetch failed", error_type=error_class.__name__,
    )
    recorded = str(logger.mock_calls)
    for private_value in (url, "private-child-path", "private-signature", detail,
                          "private-exception-body"):
        assert private_value not in recorded
