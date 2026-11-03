# Provider key cutover: implementation and current evidence

The new cutover code has not been run against the production VM. A provider key
was validated separately. The user has confirmed Keychain approval; the
transfer is in progress and its outcome must be verified independently. Treat the production 503 as unresolved until a
current public readiness check and a real generation pass after deployment.

`provider_cutover_production_entry.py` defaults to read-only preflight; its
explicit `--execute` path pins the Google project, VM, zone, instance ID, IP,
old container IDs and image digests. It requires the reviewed v4 guard files
and their loaded systemd units, an unchanged root-owned environment file, and a
matching key-file config overlay. The v4 guard boot fixture passed in a
separate disposable VM; this is not evidence of installation on production.

The transition holds the shared backup lock, creates stopped candidates and a
portless equivalent probe, and durably records candidate/probe ownership and
individual Docker operations. It drains nginx, sends the old API SIGTERM and
waits for clean exit, then checks the worker, DB and broker before stopping the
old worker. The portless probe checks the broker and DB again, requests a
synthetic JSON object and synthetic image once each, validates the stored image
and removes its own prefix. Only after that does it start the new API, check
its mounted file identities and readiness, start the new worker, check its
hostname and queue, and reopen nginx. The final HTTPS check verifies TLS and
readiness through local nginx; an external client check is still required.

Public nginx is closed during the maintenance window, but a host process or a
peer on the Docker network can reach the new API as soon as it starts. Accepted
jobs and privacy records must be preserved. If a later step fails, the handler
tries to drain nginx and APIs and waits for an active worker's queue to drain
before stopping it. A busy worker is left running. Docker timeouts or unknown
completion preserve the mutation and recovery records and must not be retried
automatically; immediate isolation is not guaranteed in that state. SIGKILL of
the executor after nginx reopens may leave the new service running with the
recovery marker until reconciliation. Existing queued work must not be deleted
or rolled back to the old key. Celery late acknowledgement and Redis AOF/RDB
were observed configured, but production replay, idempotency and zero data loss
have not been proven.

A recovery or mutation marker blocks backup/legacy recovery paths. The local
backup status check now also reports provider recovery, mutation, ownership and
installation markers to the existing binary Monitoring signal. This updated
check has not been deployed or tested with the real email channel; the existing
signal schedule and alert policy determine notification delay.

A stopped old API/worker and the private legacy environment may still contain
an older key after a successful transition. Key revocation, retention and all
legacy recovery paths require separate security verification; a successful
readiness check alone does not prove complete credential removal. Previous
uncommitted work and production data must be preserved.

Current local evidence includes a synthetic Linux Docker transition using the
production adapter with owned candidate journals, portless probe, running
bind-inode checks, TERM handling, SIGKILL recovery and cleanup. Its provider,
queue, guard-state and public ingress were stubs; a separate synthetic nginx
bind-inode replacement test passed. A
separate synthetic Redis test checked empty, queued and unacknowledged broker
states. The real provider probe, updated monitoring, public HTTPS and complete
production cutover have not run. The illustration acceptance sample and its
quality limitations are recorded separately in `LIVE_KEYCHAIN_BOOK_2026-11-03.md`.

Before operating: verify the Keychain-authorized transfer completed; install and verify the
pinned v4 guard and the exact reviewed runtime package; confirm there are no
pending install, recovery, mutation or ownership records; verify required
files, target identity and backups; run a low-cost real probe and inspect its
result; then verify readiness, worker, public HTTPS, actual generation and
backup/recovery alerts. Do not automatically delete unknown records or restart
old containers after an indeterminate operation. A partial overlay temporary
file created before atomic publication is not evidence that the final overlay
was installed; inspect ownership and digest before any cleanup.

The frozen runtime source manifest is
`infra/gcp-pilot/provider-cutover-runtime-2026-11-03-manifest.json`; verify
every file against it immediately before installation. After installing and
verifying the guard package and runtime files, the read-only preflight is
`sudo /usr/bin/python3 /opt/ai-story-book/current/scripts/provider_cutover_production_entry.py`.
It does not establish key-file access or provider readiness and reports
`cutover_ready: false` by design.
