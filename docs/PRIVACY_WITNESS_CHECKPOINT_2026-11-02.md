# Privacy journal witness checkpoint

This is a fail-closed building block and synthetic rehearsal, not an operational
restore authorization. Existing restoration quarantine requirements remain in
force.

`capture_fenced_checkpoint` holds the PostgreSQL privacy-writer fence while it
compares the current outbox and committed journal, encrypts a snapshot of the
event identifiers and payload fingerprint, writes it create-only, and reads it
back. The returned generation and ciphertext digest must be anchored in a
separately trusted channel. The GCS adapter supports create-only writes and
bounded reads; it intentionally does not infer the newest head from a listing.

`verify_checkpoint_extension` authenticates that exact supplied reference,
rejects pending, duplicate, missing, modified and per-subject gapped entries,
and checks a bounded age. It reports a verified historical prefix only. Even a
recent successful checkpoint cannot prove that no later events existed or that
every privacy mutation went through a cooperating writer. Neither capture nor
verification grants permission to serve a restored database.

`privacy_checkpoint_head.py` adds an encrypted, hash-linked sequence of up to
256 checkpoint heads. Verification compares the candidate with an exact head
reference held by the caller, checks every predecessor, and then checks the
checkpointed journal prefix. A new independently anchored namespace is required
before the chain limit. The caller must separately guarantee that the reference
is the latest one and that it survives a common source/witness failure; the
chain cannot prove those facts. A reference updated after the privacy writer
fence is released also cannot prove that no later event occurred in the gap.

The checkpoint encryption key can be generated and wrapped using an independent
256-bit recovery key (`privacy_checkpoint_keys.py`). Recovery requires that
key and the independently trusted envelope digest. The implementation does not
generate a production recovery key, configure an independent administrator, or
ensure the recovery key and reference survive a disaster. Storing them together
under the same administrator does not address joint loss or rollback. If the
key, trusted reference, witness, or proof of latest coverage is unavailable,
the restore must remain quarantined.

Focused tests cover corrupted or stale references, gaps, cancellation during
witness writes, envelope recovery, and create-only storage behavior. The
offline rehearsal uses disposable PostgreSQL and MinIO inside a network-none
container; its GCS JSON API is emulated over local MinIO buckets. It captures
source events, recovers the key in another process, verifies a subsequent
event extension and two linked heads, and rejects removal of a captured event
or presentation of the old head. It does not test GCS
IAM, retention, administrator independence, live credentials, or live data.
[The latest local run](acceptance/privacy-witness-synthetic-2026-11-02/offline-restore-5cb0f9cc1e70a267cbf7c481a185a256.json)
reported `PASSED`, with `restore_authorized: false`.

The [real GCS synthetic test](acceptance/privacy-witness-synthetic-2026-11-02/gcs-synthetic-result.json)
used two temporary, run-owned buckets, random disposable encryption keys, and
fictional events. It exercised create-only writes, wrapped-key recovery, head
chain verification, rejection of an older candidate and a missing event, and
deleted the test objects and buckets. Both buckets used the same Google
account; the source checkpoint input was fabricated for this cloud contract
test, and no independent administrator or current production head was tested.

## Uninstalled operator controls

- `scripts/enroll_witness_key.py` can issue an inactive random witness key,
  store its encrypted envelope, and export the envelope and trusted reference
  as new private files. The separately generated recovery key is an input;
  the script never prints it. Partial enrollment is not activation and must
  be inspected without overwriting existing files.
- `scripts/recover_witness_key.py` can recover from GCS or from an independently
  copied encrypted envelope when Google is unavailable. It checks the trusted
  envelope digest and AES-GCM authentication and creates a new 0600 key file
  without overwriting an existing path. Each witness key needs its own tested
  recovery material. This does not recover the existing production journal key.
- `scripts/run_privacy_witness_monitor.py` is disabled by default. When
  configured, it fences the selected PostgreSQL source, checks both journal
  replicas, and compares the exact externally supplied head and current event
  count. Missing inputs, stale references, an unanchored event, disagreement,
  or provider failure produce `ALERT`. Any result keeps restore unauthorized.
- `scripts/publish_privacy_witness_health.py` plus the adjacent
  `infra/gcp-pilot/asb-privacy-witness-*` service, timer and Monitoring policy
  template can publish a binary failed-or-missing alert. They are not installed
  or connected to the email channel. Test both a failed check and a missing
  signal after independent infrastructure is provisioned.

The recovery key, exported envelope and exact latest head reference must be
retained in a separately controlled failure domain and independently tested.
A reference file on the same VM or two buckets controlled by the same Google
administrator are not independent. The current monitoring CLI reads a local
reference supplied by an external control; authenticating and durably updating
that control has not been implemented or verified. Until that exists, the
signal cannot prove the head is actually latest, especially after simultaneous
source and witness loss or rollback. Source mutations after a fenced check can
also precede the next checkpoint and alert. Do not enable operational recovery
or describe this as a complete disaster-recovery guarantee on this evidence.

## Second-host observation (not installed)

`privacy_witness_receipt.py` can sign a synthetic snapshot observation with an
Ed25519 key and verify its signature, exact locally trusted head and age on a
second machine. `scripts/mac_privacy_witness_observer.py` fails closed on a
missing, stale, modified, or mismatched receipt and always returns
`restore_authorized: false`. A valid signature proves the signing key holder
created the report; it does not prove the source is reachable or that the
source report is truthful. If the source fails just after issuing a receipt,
the failure may not be detected until its configured maximum age expires.

The `infra/macos/com.aistorybook.privacy-witness.plist.template` launchd job
is only a template and logs fixed success/failure messages locally. It is not
installed, does not wake a sleeping Mac, is not a reliable user notification,
and provides no external alert delivery. An authenticated feed, independently
protected latest reference and actual alert delivery remain to be built and
verified; no production values or keys were copied to the Mac. As inspected,
the Mac has only one physical internal disk and no separate external disk.
Its disk and Google VM are separate machines, but a local file is not proof of
independent administration and can be lost or rolled back with the Mac.
