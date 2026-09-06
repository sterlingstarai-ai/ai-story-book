"""Read-only private media preflight. Uses API settings or explicitly exported production settings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

import httpx
from src.core.config import settings
from src.services.storage import _public_url_bases, canonical_media_url, get_s3_client, media_url


def verify(public_base: str, key: str) -> int:
    if public_base.rstrip('/') + '/' not in _public_url_bases():
        print("INCONCLUSIVE: base must match S3_PUBLIC_URL or a configured legacy base.")
        return 2
    try:
        # A random/nonexistent key returning 404 is never proof of privacy.
        get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
        signed = media_url(canonical_media_url(key))
        from urllib.parse import quote, urlsplit, urlunsplit
        anonymous = f"{public_base.rstrip('/')}/{quote(key, safe='/')}"
        parsed = urlsplit(signed)
        unsigned_api = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            # Stream only headers: no need to download a family's full media file.
            with client.stream('GET', signed, headers={'Range': 'bytes=0-0'}) as response:
                if response.status_code not in {200, 206}:
                    print("INCONCLUSIVE: signed download did not succeed.")
                    return 2
            for url in {anonymous, unsigned_api}:
                with client.stream('GET', url, headers={'Range': 'bytes=0-0'}) as response:
                    if response.status_code in {200, 206}:
                        print("PUBLIC: anonymous media access is possible; close bucket/CDN access.")
                        return 1
                    if response.status_code not in {403, 404}:
                        print("INCONCLUSIVE: anonymous download returned an unexpected status.")
                        return 2
    except Exception:
        # SDK/HTTP exception strings may include signed URLs or object identifiers.
        print("INCONCLUSIVE: object existence or connectivity could not be verified.")
        return 2
    print("PRIVATE: existing object downloads with a signature; anonymous reads are blocked.")
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("usage: check-bucket-exposure.sh <configured public base> <existing test object key>")
        raise SystemExit(2)
    raise SystemExit(verify(sys.argv[1], sys.argv[2]))
