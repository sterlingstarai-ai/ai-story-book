"""
Storage Service: S3/Minio 파일 업로드
"""

import asyncio
import inspect
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import httpx
import structlog
from urllib.parse import urlparse
import ipaddress
import socket

from src.core.config import settings
from src.core.errors import StorageError

logger = structlog.get_logger()

# Cache for bucket existence check (protected by lock)
_bucket_verified = False
_bucket_lock = asyncio.Lock()

# Allowed domains for image fetching (SSRF protection)
ALLOWED_IMAGE_DOMAINS = {
    "oaidalleapiprodscus.blob.core.windows.net",  # OpenAI DALL-E
    "replicate.delivery",  # Replicate
    "fal.media",  # FAL.ai
    "s3.amazonaws.com",
    "r2.cloudflarestorage.com",
}


def _is_url_allowed(url: str) -> bool:
    """Validate URL for SSRF protection (fail-closed)"""
    try:
        parsed = urlparse(url)

        # Only allow http and https
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Check against allowed domains + S3 endpoint from settings
        s3_host = urlparse(settings.s3_endpoint).hostname or ""
        s3_public_host = urlparse(settings.s3_public_url).hostname or ""
        allowed = ALLOWED_IMAGE_DOMAINS | {s3_host, s3_public_host}

        # Check exact match or subdomain match
        for domain in allowed:
            if domain and (hostname == domain or hostname.endswith(f".{domain}")):
                return True

        # Block private IP ranges (fail-closed)
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                logger.warning("Blocked private IP in URL", hostname=hostname)
                return False
        except (socket.gaierror, ValueError):
            # SECURITY: Fail-closed - block if we can't resolve
            logger.warning(
                "DNS resolution failed for URL validation", hostname=hostname
            )
            return False

        return False
    except Exception:
        return False


def get_s3_client():
    """Get S3 client configured for Minio or AWS S3"""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4"),
    )


async def _call_s3(method, **kwargs):
    """
    Execute S3 client method that may be sync (boto3) or async (mock/testing).
    """
    result = method(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def ensure_bucket_exists():
    """Ensure the bucket exists, create if not. Thread-safe with asyncio.Lock."""
    global _bucket_verified

    if _bucket_verified:
        return

    async with _bucket_lock:
        # Double-check after acquiring lock
        if _bucket_verified:
            return

        client = get_s3_client()
        try:
            await _call_s3(client.head_bucket, Bucket=settings.s3_bucket)
            _bucket_verified = True
        except ClientError:
            try:
                await _call_s3(client.create_bucket, Bucket=settings.s3_bucket)
                logger.info("Created bucket", bucket=settings.s3_bucket)
                logger.warning(
                    "Bucket created without public policy - configure access policy manually"
                )
                _bucket_verified = True
            except ClientError as e:
                logger.error("Failed to create bucket", error=str(e))
                raise StorageError(f"Failed to create bucket: {e}")


def key_from_public_url(url: Optional[str]) -> Optional[str]:
    """저장된 공개 URL({s3_public_url}/{key})에서 S3 키를 복원한다. 우리 버킷이 아니면 None."""
    base = (settings.s3_public_url or "").rstrip("/") + "/"
    if url and base != "/" and url.startswith(base):
        return url[len(base):]
    return None


async def get_object_bytes(key: str) -> tuple[bytes, str]:
    """S3 객체를 키로 읽어 (bytes, content_type) 반환 — 공유 이미지 토큰 프록시용."""
    client = get_s3_client()
    resp = await _call_s3(client.get_object, Bucket=settings.s3_bucket, Key=key)
    body = resp["Body"]
    data = body.read()
    if inspect.isawaitable(data):
        data = await data
    content_type = resp.get("ContentType") or "application/octet-stream"
    return data, content_type


async def upload_image_from_url(
    source_url: str,
    book_id: str,
    filename: str,
) -> str:
    """
    Download image from URL and upload to S3

    Args:
        source_url: URL to download image from
        book_id: Book ID for folder path
        filename: Target filename (e.g., "cover.png", "p1.png")

    Returns:
        Public URL of uploaded file
    """
    # SSRF protection: validate URL before fetching
    if not _is_url_allowed(source_url):
        logger.warning("Image URL blocked by SSRF protection", url=source_url[:100])
        raise StorageError(f"URL not allowed: {source_url[:50]}...")

    await ensure_bucket_exists()

    # Download image
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(source_url)
        if response.status_code != 200:
            raise StorageError(f"Failed to download image: {response.status_code}")
        image_data = response.content

    # Determine content type
    content_type = response.headers.get("content-type", "image/png")

    # Upload to S3
    s3_key = f"books/{book_id}/{filename}"

    try:
        s3_client = get_s3_client()
        await _call_s3(
            s3_client.put_object,
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=image_data,
            ContentType=content_type,
        )
    except ClientError as e:
        logger.error(f"Failed to upload to S3: {e}")
        raise StorageError(f"Failed to upload: {e}")

    # Return public URL
    return f"{settings.s3_public_url}/{s3_key}"


async def upload_file(
    data: bytes,
    book_id: str,
    filename: str,
    content_type: str = "application/octet-stream",
) -> str:
    """
    Upload file data to S3

    Returns:
        Public URL of uploaded file
    """
    await ensure_bucket_exists()

    s3_key = f"books/{book_id}/{filename}"

    try:
        s3_client = get_s3_client()
        await _call_s3(
            s3_client.put_object,
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=data,
            ContentType=content_type,
        )
    except ClientError as e:
        logger.error(f"Failed to upload to S3: {e}")
        raise StorageError(f"Failed to upload: {e}")

    return f"{settings.s3_public_url}/{s3_key}"


async def _delete_prefix_keys(prefix: str) -> list[str]:
    """prefix 하 모든 객체를 삭제하고, **삭제에 실패한 키 목록**을 반환한다([] = 전건 성공).

    H8: 이전 구현은 ClientError를 내부에서 삼켜(raise 안 함) 지배적 실패 클래스(S3 API
    오류)가 항상 '실패 0'으로 보고됐다. 이제 (a) list_objects_v2를 페이지네이션해 전체 키를
    열거하고, (b) delete_objects 응답의 per-key 'Errors'를 실패로 합산하며, (c) ClientError
    발생 시에도 삼키지 않고 해당 prefix를 실패로 표면화한다. 호출부가 status=partial 판정에 쓴다.
    """
    s3_client = get_s3_client()
    failed: list[str] = []
    total_deleted = 0
    continuation: Optional[str] = None
    try:
        while True:
            kwargs = {"Bucket": settings.s3_bucket, "Prefix": prefix}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            response = await _call_s3(s3_client.list_objects_v2, **kwargs)

            objects = response.get("Contents", [])
            if objects:
                del_resp = await _call_s3(
                    s3_client.delete_objects,
                    Bucket=settings.s3_bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
                errors = del_resp.get("Errors", []) or []
                failed.extend(e["Key"] for e in errors if e.get("Key"))
                total_deleted += len(objects) - len(errors)

            if response.get("IsTruncated"):
                continuation = response.get("NextContinuationToken")
                if not continuation:
                    break
            else:
                break
    except ClientError as e:
        logger.error("S3 delete failed", prefix=prefix, error=str(e))
        # 삼키지 않는다 — prefix 전체를 실패로 표면화(아동 PII 잔존을 관측 가능하게).
        failed.append(f"{prefix}*")

    if total_deleted:
        logger.info("Deleted objects under prefix", prefix=prefix, count=total_deleted)
    return failed


async def delete_book_files(book_id: str) -> list[str]:
    """Delete all files for a book. Returns keys that FAILED to delete ([] = ok, H8)."""
    return await _delete_prefix_keys(f"books/{book_id}/")


async def delete_keys(keys: list[str]) -> list[str]:
    """명시된 S3 키들을 삭제하고 **삭제 실패한 키 목록**을 반환한다([] = 전건 성공, N1).

    파이프라인 이미지가 books/{id}/ prefix 밖(images/{provider}/{uuid} 등)에 저장돼도
    저장된 image_url에서 역산한 키로 직접 파기하기 위한 헬퍼. delete_objects는 1회 1000개
    한도라 청크 분할하고, per-key Errors·ClientError를 H8 계약대로 실패로 표면화한다.
    """
    keys = [k for k in dict.fromkeys(keys) if k]  # 중복 제거 + 빈 값 제외(순서 보존)
    if not keys:
        return []
    s3_client = get_s3_client()
    failed: list[str] = []
    for i in range(0, len(keys), 1000):
        chunk = keys[i : i + 1000]
        try:
            del_resp = await _call_s3(
                s3_client.delete_objects,
                Bucket=settings.s3_bucket,
                Delete={"Objects": [{"Key": k} for k in chunk]},
            )
            errors = del_resp.get("Errors", []) or []
            failed.extend(e["Key"] for e in errors if e.get("Key"))
        except ClientError as e:
            logger.error("S3 delete_keys failed", count=len(chunk), error=str(e))
            failed.extend(chunk)  # 삼키지 않는다 — 청크 전체를 실패로 표면화
    return failed


class StorageService:
    """Storage Service 클래스"""

    async def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload bytes data to S3 with custom key

        Args:
            data: File data as bytes
            key: Full S3 key path (e.g., "books/123/audio/page_1.mp3")
            content_type: MIME type

        Returns:
            Public URL of uploaded file
        """
        await ensure_bucket_exists()

        try:
            s3_client = get_s3_client()
            await _call_s3(
                s3_client.put_object,
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as e:
            logger.error(f"Failed to upload to S3: {e}")
            raise StorageError(f"Failed to upload: {e}")

        return f"{settings.s3_public_url}/{key}"

    async def upload_image_from_url(
        self,
        source_url: str,
        book_id: str,
        filename: str,
    ) -> str:
        """Wrapper for upload_image_from_url function"""
        return await upload_image_from_url(source_url, book_id, filename)

    async def upload_file(
        self,
        data: bytes,
        book_id: str,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Wrapper for upload_file function"""
        return await upload_file(data, book_id, filename, content_type)

    async def delete_prefix(self, prefix: str) -> list[str]:
        """prefix 하 모든 객체 삭제(동의 철회 시 아동 사진 파기 등).

        H8: 반환값을 '삭제 실패 키 목록'으로 변경([] = 전건 성공). ClientError·per-key
        Errors를 삼키지 않고 표면화해 호출부가 status=partial을 판정하게 한다.
        """
        return await _delete_prefix_keys(prefix)


# 싱글톤 인스턴스
storage_service = StorageService()
