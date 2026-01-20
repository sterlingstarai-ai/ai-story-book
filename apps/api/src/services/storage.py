"""
Storage Service: S3/Minio 파일 업로드
"""
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import httpx
from typing import Optional
import uuid
from datetime import datetime
import structlog

from src.core.config import settings
from src.core.errors import StorageError

logger = structlog.get_logger()

# Cache for bucket existence check
_bucket_verified = False


def get_s3_client():
    """Get S3 client configured for Minio or AWS S3"""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4"),
    )


async def ensure_bucket_exists():
    """Ensure the bucket exists, create if not. Cached after first check."""
    global _bucket_verified

    if _bucket_verified:
        return

    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
        _bucket_verified = True
    except ClientError:
        try:
            client.create_bucket(Bucket=settings.s3_bucket)
            # Set bucket policy for public read
            import json
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{settings.s3_bucket}/*"
                    }
                ]
            }
            client.put_bucket_policy(
                Bucket=settings.s3_bucket,
                Policy=json.dumps(policy)
            )
            logger.info(f"Created bucket: {settings.s3_bucket}")
            _bucket_verified = True
        except ClientError as e:
            logger.error(f"Failed to create bucket: {e}")
            raise StorageError(f"Failed to create bucket: {e}")


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
        s3_client.put_object(
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
        s3_client.put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=data,
            ContentType=content_type,
        )
    except ClientError as e:
        logger.error(f"Failed to upload to S3: {e}")
        raise StorageError(f"Failed to upload: {e}")

    return f"{settings.s3_public_url}/{s3_key}"


async def delete_book_files(book_id: str):
    """Delete all files for a book"""
    try:
        s3_client = get_s3_client()
        prefix = f"books/{book_id}/"

        # List objects
        response = s3_client.list_objects_v2(
            Bucket=settings.s3_bucket,
            Prefix=prefix,
        )

        # Delete objects
        objects = response.get("Contents", [])
        if objects:
            s3_client.delete_objects(
                Bucket=settings.s3_bucket,
                Delete={
                    "Objects": [{"Key": obj["Key"]} for obj in objects]
                },
            )
            logger.info(f"Deleted {len(objects)} files for book {book_id}")
    except ClientError as e:
        logger.error(f"Failed to delete files: {e}")
        # Don't raise - deletion failure shouldn't block other operations


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
            s3_client.put_object(
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


# 싱글톤 인스턴스
storage_service = StorageService()
