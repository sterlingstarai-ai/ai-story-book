# Storage purge integrity — 2026-11-02

This is local implementation and test evidence, not production deployment or
proof that an operational restore is safe.

The storage purge worker keeps tasks retryable when a prefix listing cannot be
completed, a listing contains a key outside its requested prefix, or a delete
response does not account for every requested key. A repeated or missing
continuation token also fails closed. The implementation uses the default
verbose S3 `DeleteObjects` response contract described in the
[AWS API documentation](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html).
Purge logs and `last_error` no longer retain raw provider exceptions or object
paths. Existing task targets are still needed for retries.

Verification on this checkout:

- 75 focused API tests passed, including purge, photo erasure, and privacy
  journal replay cases; Ruff passed on the modified and added Python files.
- A disposable local MinIO instance deleted 1,002 synthetic objects across
  listing pages while retaining an unrelated object. The container was removed.

Before deployment, verify the actual Neon S3-compatible provider's verbose
multi-delete response using only a newly created, uniquely named test object;
the local MinIO result does not establish Neon compatibility. These changes do
not establish independently complete privacy-event records, recover the journal
key, authorize an operational restore, or delete old versions from versioned
buckets. Those require separate operator verification and recovery controls.
