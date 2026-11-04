"""
Storage Service: S3/Minio 파일 업로드
"""

import asyncio
import inspect
from functools import lru_cache, partial
from typing import Optional

import boto3
from anyio import to_thread
from botocore.config import Config
from botocore.exceptions import ClientError
import httpx
import structlog
from urllib.parse import urlparse, unquote
import ipaddress
import socket

from src.core.config import settings
from src.core.errors import StorageError

logger = structlog.get_logger()

# Cache for bucket existence check (protected by lock)
_bucket_verified = False
_bucket_lock = asyncio.Lock()
_MAX_OBJECT_BYTES = 20 * 1024 * 1024
_MAX_PURGE_LIST_PAGES = 10000

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


def get_s3_client(*, bounded_upload=False):
    """Get S3 client configured for Minio or AWS S3"""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": settings.s3_addressing_style},
                      **({'connect_timeout': 5, 'read_timeout': 30,
                          'retries': {'mode': 'standard', 'total_max_attempts': 2}}
                         if bounded_upload else {})),
    )


async def _call_s3(method, *args, **kwargs):
    """
    Execute S3 client method that may be sync (boto3) or async (mock/testing).
    """
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    result = await to_thread.run_sync(partial(method, *args, **kwargs))
    if inspect.isawaitable(result):
        return await result
    return result


async def _write_s3(method, *args, **kwargs):
    if settings.testing:
        return await _call_s3(method, *args, **kwargs)
    from src.services.storage_write_guard import guarded_media_write

    async with guarded_media_write():
        return await _call_s3(method, *args, **kwargs)


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
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if not settings.s3_auto_create_bucket or code not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError("Configured private bucket is unavailable or access was denied") from None
            try:
                options = {"Bucket": settings.s3_bucket}
                if settings.s3_region != "us-east-1":
                    options["CreateBucketConfiguration"] = {"LocationConstraint": settings.s3_region}
                await _write_s3(client.create_bucket, **options)
                logger.info("Created bucket", bucket=settings.s3_bucket)
                logger.warning(
                    "Bucket created without public policy - configure access policy manually"
                )
                _bucket_verified = True
            except ClientError:
                logger.error("Failed to create private bucket")
                raise StorageError("Failed to create private bucket") from None


def _public_url_bases() -> list[str]:
    """키 역산에 인정할 공개 URL prefix 목록(현재 + 과거 도메인).

    R4: prefix를 '현재 s3_public_url' 하나로만 보면, CDN/도메인을 바꾸는 순간 **그 전에 저장된
    전 객체**의 역산이 None이 되어 파기가 조용한 no-op이 된다(아동 likeness 영구 잔존).
    `S3_LEGACY_PUBLIC_URLS`(콤마 구분)에 과거 base를 남겨두면 계속 파기 대상이 된다.
    """
    bases: list[str] = []
    for raw in [
        settings.s3_public_url,
        *(settings.s3_legacy_public_urls or "").split(","),
    ]:
        cleaned = (raw or "").strip().rstrip("/")
        if cleaned:
            bases.append(cleaned + "/")
    return list(dict.fromkeys(bases))


def key_from_public_url(url: Optional[str]) -> Optional[str]:
    """저장된 공개 URL({s3_public_url}/{key})에서 S3 키를 복원한다. 우리 버킷이 아니면 None."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    bases = _public_url_bases() + [
        f"{endpoint.rstrip('/')}/{settings.s3_bucket}/"
        for endpoint in [settings.s3_endpoint, settings.s3_download_endpoint]
        if endpoint
    ]
    # Re-signing and deletion must also recognize our configured bucket when
    # an AWS endpoint uses virtual-hosted addressing. Never accept other buckets.
    for endpoint in [settings.s3_endpoint, settings.s3_download_endpoint]:
        if endpoint and settings.s3_addressing_style in {"virtual", "auto"}:
            target = urlparse(endpoint)
            bases.append(target._replace(netloc=f"{settings.s3_bucket}.{target.netloc}",
                                         path=target.path.rstrip("/") + "/").geturl())
    for base in bases:
        expected = urlparse(base)
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
            continue
        if parsed.path.startswith(expected.path):
            key = unquote(parsed.path[len(expected.path):])
            if key and all(part not in {"", ".", ".."} for part in key.split('/')):
                return key
    return None


def canonical_media_url(key: str) -> str:
    """Stable DB reference; this URL does not imply anonymous bucket access."""
    from urllib.parse import quote
    return f"{settings.s3_public_url.rstrip('/')}/{quote(key, safe='/')}"


def voice_sample_prefix(user_key: str) -> str:
    """Opaque owner namespace: object URLs must never contain the bearer credential."""
    import hashlib
    owner = hashlib.sha256(f"voice-samples:v2:{user_key}".encode()).hexdigest()
    return f"voice-samples/v2/{owner}/"


@lru_cache(maxsize=4)
def _signing_client(endpoint: str, access_key: str, secret_key: str, region: str, addressing_style: str):
    return boto3.client(
        "s3", endpoint_url=endpoint,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": addressing_style}),
    )


def media_url(url: Optional[str], *, expires_in: Optional[int] = None) -> Optional[str]:
    """Sign a known-owned asset at the response/provider boundary, never during persistence.

    Callers must first check ownership; never pass arbitrary client-submitted URLs here.
    External legacy assets and deliberate placeholders are returned unchanged.
    """
    key = key_from_public_url(url)
    if key is None:
        return url
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise StorageError("Media download signing is not configured")
    client = _signing_client(
        settings.s3_download_endpoint or settings.s3_endpoint,
        settings.s3_access_key, settings.s3_secret_key,
        settings.s3_region, settings.s3_addressing_style,
    )
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in or settings.s3_download_ttl_seconds,
    )


async def get_object_bytes(key: str) -> tuple[bytes, str]:
    """S3 객체를 키로 읽어 (bytes, content_type) 반환 — 공유 이미지 토큰 프록시용."""
    client = await _call_s3(get_s3_client)
    resp = await _call_s3(client.get_object, Bucket=settings.s3_bucket, Key=key)
    body = resp["Body"]
    try:
        if resp.get("ContentLength", 0) > _MAX_OBJECT_BYTES:
            raise StorageError("Media object exceeds download size limit")
        data = await _call_s3(body.read, _MAX_OBJECT_BYTES + 1)
        if len(data) > _MAX_OBJECT_BYTES:
            raise StorageError("Media object exceeds download size limit")
    finally:
        await _call_s3(body.close)
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
        await _write_s3(
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
        await _write_s3(
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


def _validated_prefix_objects(response, prefix: str) -> list:
    """Reject contradictory page metadata before claiming an empty prefix."""
    if not isinstance(response, dict) or type(response.get('IsTruncated')) is not bool:
        raise ValueError('invalid list response')
    objects = response.get('Contents', [])
    if (not isinstance(objects, list)
            or ('KeyCount' in response and (type(response['KeyCount']) is not int
                                            or response['KeyCount'] != len(objects)))
            or response.get('CommonPrefixes', []) != []
            or ('Prefix' in response and response['Prefix'] != prefix)
            or ('Name' in response and response['Name'] != settings.s3_bucket)
            or any(not isinstance(obj, dict) or not isinstance(obj.get('Key'), str)
                   or not obj['Key'].startswith(prefix) for obj in objects)):
        raise ValueError('invalid object listing')
    keys = [obj['Key'] for obj in objects]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate object listing')
    return objects


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
    seen_tokens: set[str] = set()
    page_count = 0
    try:
        while True:
            page_count += 1
            if page_count > _MAX_PURGE_LIST_PAGES:
                raise ValueError("storage listing page limit exceeded")
            kwargs = {"Bucket": settings.s3_bucket, "Prefix": prefix}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            response = await _call_s3(s3_client.list_objects_v2, **kwargs)

            objects = _validated_prefix_objects(response, prefix)
            truncated = response.get("IsTruncated")
            next_token = response.get("NextContinuationToken")
            if truncated and (not isinstance(next_token, str) or not next_token or next_token in seen_tokens):
                raise ValueError("incomplete or repeated listing token")
            if objects:
                chunk = [obj["Key"] for obj in objects]
                del_resp = await _write_s3(
                    s3_client.delete_objects,
                    Bucket=settings.s3_bucket,
                    Delete={"Objects": [{"Key": key} for key in chunk]},
                )
                chunk_failed = _delete_response_failures(del_resp, chunk)
                failed.extend(chunk_failed)
                total_deleted += len(chunk) - len(chunk_failed)

            if truncated:
                continuation = next_token
                seen_tokens.add(continuation)
            else:
                break
        if total_deleted and not failed:
            # A deletion can change later pages. Re-list the prefix before
            # declaring the purge complete, including providers that skip or
            # truncate entries unexpectedly. This is a point-in-time check,
            # not a fence against a later concurrent upload.
            remaining = await _call_s3(s3_client.list_objects_v2, Bucket=settings.s3_bucket,
                                       Prefix=prefix, MaxKeys=1)
            if (_validated_prefix_objects(remaining, prefix)
                    or remaining['IsTruncated'] is not False):
                raise ValueError("storage prefix is not verified empty")
    except (ClientError, ValueError, TypeError, KeyError):
        logger.error("S3 prefix deletion incomplete")
        # 삼키지 않는다 — prefix 전체를 실패로 표면화(아동 PII 잔존을 관측 가능하게).
        failed.append(f"{prefix}*")

    if total_deleted:
        logger.info("Deleted objects under prefix", count=total_deleted)
    return failed


async def copy_object_to_new_key(source_url: str, new_key: str) -> Optional[str]:
    """우리 버킷 안의 객체를 새 키로 **서버측 복사**하고 새 공개 URL을 반환한다 (H6).

    연령 리텔은 삽화를 재생성하지 않고 원본 URL을 그대로 복사해 두 책이 **같은 S3 객체**를
    가리켰다. 삭제 경로(`collect_book_image_keys` → 역산 파기)는 배타 소유를 가정하므로,
    둘 중 하나만 지워도 남은 책의 표지·전 페이지가 404가 된다.

    다운로드/업로드가 아니라 S3 `copy_object` (서버측)라 대역폭·지연이 거의 없다.
    우리 버킷이 아닌 URL(역산 불가)이면 None — 호출부가 공유 여부를 판단한다.
    """
    source_key = key_from_public_url(source_url)
    if not source_key:
        return None

    await ensure_bucket_exists()
    client = get_s3_client()
    try:
        await _write_s3(
            client.copy_object,
            Bucket=settings.s3_bucket,
            CopySource={"Bucket": settings.s3_bucket, "Key": source_key},
            Key=new_key,
        )
    except ClientError as e:
        logger.error(
            "Failed to copy object", source_key=source_key, new_key=new_key, error=str(e)
        )
        raise StorageError(f"Failed to copy object: {e}")

    return f"{settings.s3_public_url.rstrip('/')}/{new_key}"


def book_file_prefix(book_id: str) -> str:
    """책 파일 prefix — durable 파기 큐(outbox)가 같은 대상을 재실행할 수 있도록 노출."""
    return f"books/{book_id}/"


def character_file_prefix(character_id: str) -> str:
    """캐릭터 원본(아동 사진/그림) prefix — 위와 동일한 이유로 상수화."""
    return f"characters/{character_id}/"


def mask_file_prefix(book_id: str) -> str:
    """인페인트 마스크(사용자 업로드) prefix (F2/books.py:895).

    마스크는 `masks/{book_id}/…` 에 저장되나 books/{id}/ prefix 밖이라 책 파기가 놓친다.
    책이 지워지는 모든 경로(단건·계정·동의철회)에서 이 prefix 도 함께 durable 파기한다.
    """
    return f"masks/{book_id}/"


async def delete_book_files(book_id: str) -> list[str]:
    """Delete all files for a book. Returns keys that FAILED to delete ([] = ok, H8)."""
    return await _delete_prefix_keys(book_file_prefix(book_id))


def _delete_response_failures(response, chunk: list[str]) -> list[str]:
    """Require the default verbose S3 response to account for every key."""
    if not isinstance(response, dict):
        return list(chunk)
    errors = response.get("Errors", [])
    deleted = response.get("Deleted", [])
    if not isinstance(errors, list) or not isinstance(deleted, list):
        return list(chunk)
    allowed = set(chunk)
    if any(not isinstance(entry, dict) or not isinstance(entry.get("Key"), str)
           or entry["Key"] not in allowed for entry in errors + deleted):
        return list(chunk)
    failed = {entry["Key"] for entry in errors}
    succeeded = {entry["Key"] for entry in deleted}
    if failed & succeeded or failed | succeeded != allowed:
        return list(chunk)
    return list(dict.fromkeys(entry["Key"] for entry in errors))


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
            del_resp = await _write_s3(
                s3_client.delete_objects,
                Bucket=settings.s3_bucket,
                Delete={"Objects": [{"Key": k} for k in chunk]},
            )
            failed.extend(_delete_response_failures(del_resp, chunk))
        except ClientError:
            logger.error("S3 delete_keys failed", count=len(chunk))
            failed.extend(chunk)  # 삼키지 않는다 — 청크 전체를 실패로 표면화
    return failed


class StorageService:
    """Storage Service 클래스"""

    async def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/octet-stream",
        *, bounded_upload: bool = False,
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
            s3_client = get_s3_client(bounded_upload=True) if bounded_upload else get_s3_client()
            await _write_s3(
                s3_client.put_object,
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except ClientError:
            # Provider exceptions can contain object keys or credentials.
            logger.error("Failed to upload to S3")
            raise StorageError("Failed to upload to storage") from None

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
