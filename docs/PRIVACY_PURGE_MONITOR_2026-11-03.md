# Privacy erasure queue monitoring

## Pilot installation update

On 2026-11-03 the independent monitor was installed on `asb-free-test` in
project `gen-lang-client-0308507618`. The timer is enabled and active, its
first service invocation reported success, and the dedicated alert policy
`projects/gen-lang-client-0308507618/alertPolicies/16229069859584981609` is
enabled with the previously approved email channel. This confirms provider
acceptance of the first binary signal and configured routing, not delivery of
an email or successful detection of every failure. Synthetic unhealthy and
missing-signal checks and actual notification receipt remain for the final
integrated verification. The older observations and preparation notes below
describe the state before installation.

The VM has a separately generated role with SELECT on the seven queue columns
needed by the monitor, no observed effective table write privilege, and a
read-only transaction default. Its credentials are held only in the root-owned
`/etc/ai-story-book/pilot/private/privacy-purge-monitor-db.env`; the root-owned
`privacy-purge-watch.env` points to that file and the existing Neon CA. The
source was checked against both API and worker configurations. Existing app
roles, data, API, worker, proxy, backup timer, and backup policy were not changed.
The monitor reuses the existing app virtualenv and the VM service account's
existing Monitoring write permission. Bundle manifest SHA-256 is
`5737e4bc4b0c879aa4a13166f25a1d85ee9360c02152b0c913cf85e5231ae646`.
Root-owned installer staging for recovery is
`/var/tmp/asb-purge-stage-281f99ac6d1f6151`; monitor files are at
`/opt/ai-story-book/privacy-purge-monitor/`.

To disable the new policy before stopping the timer, an authorized operator
can run the following and verify that the policy is disabled. This does not
modify the existing backup policy:

```sh
gcloud alpha monitoring policies update projects/gen-lang-client-0308507618/alertPolicies/16229069859584981609 --project gen-lang-client-0308507618 --no-enabled
sudo python3 /var/tmp/asb-purge-stage-281f99ac6d1f6151/manage_privacy_purge_monitor.py rollback --execute --policy-disabled
```

The rollback retains its own files and the dedicated read-only role and does
not touch user data. Their eventual removal requires separately checking that
no remaining monitor uses them; never remove existing app credentials. A failed
pre-install attempt was blocked because local archive metadata and then Python
bytecode added files outside the manifest; the owned partial installation was
verified and removed, the bundle was retransferred, and bytecode generation was
disabled during the install preflight. The first owned staging directory was
removed after its manifest and contents were checked. One earlier candidate
remains at `/var/tmp/asb-purge-stage-b03671b961ae4fde`: its manifest and files
were checked against the candidate and no runtime credential files were found,
but it was retained because its ownership by this run was not recorded
unambiguously. The separately identified recovery staging path above is also
retained intentionally.

## Prepared monitor bundle update (not yet applied)

`scripts/update_privacy_purge_monitor.py` prepares a separate bundle switch
without editing the systemd units, Cloud Monitoring policy, backup timer or
application. It needs the adjacent `manage_privacy_purge_monitor.py` and a
fresh root-owned bundle built and transferred under a new private staging
directory. Before switching, it verifies the VM, configuration, current and
candidate manifest hashes, source file hashes, installed unit hashes, matching
unit files in the candidate, and a read-only candidate queue check. It leaves
the previous release in place. It pauses the monitor timer, waits for any old
invocation to finish, atomically switches the `current` symlink, starts the
new service once, then restarts the timer. A normal service-start failure
attempts to restore the old symlink and restart the old timer; it never removes
either bundle or modifies the Cloud policy. Provider acceptance of a signal is
not proof of an alert email.

After final isolated validation and a separate source/bundle SHA review, the
operator can switch the monitor before enabling any app version that produces
the new `voice_sample_upload_guard` reason:

```sh
sudo python3 /absolute/root-owned/staging/update_privacy_purge_monitor.py --execute --bundle /absolute/root-owned/staging/bundle --expected-current-sha256 CURRENT_REVIEWED_MANIFEST_SHA256 --manifest-sha256 NEXT_REVIEWED_MANIFEST_SHA256
```

To switch back to the original `release` directory, use the current and prior
reviewed digests in reverse order. The command below rechecks the retained
release and unit hashes; it does not delete the candidate:

```sh
sudo python3 /absolute/root-owned/staging/update_privacy_purge_monitor.py --execute --bundle /opt/ai-story-book/privacy-purge-monitor/release --reuse-existing-target release --expected-current-sha256 CURRENT_REVIEWED_MANIFEST_SHA256 --manifest-sha256 PRIOR_REVIEWED_MANIFEST_SHA256
```

For a later release named `release-<sha256>`, pass that exact name to
`--reuse-existing-target` and its absolute directory to `--bundle`. If the
updater or VM is killed after the timer stops, or if restarting the timer
fails, automatic rollback cannot be guaranteed. Inspect the retained current
link, unit and policy status, confirm the intended manifest, and manually
restore the timer or previous release; the separate missing-signal policy
should alert after its configured delay. Concurrent operators and service
changes require a fresh review. No monitor update or rollback has been
executed or tested yet.

Read-only inspection of the Google Cloud pilot project's alert policies found one
enabled backup-health policy, covering backup failure and missing backup-health
signals. It did not show a dedicated policy for privacy erasure tasks. The
backup code can refuse a snapshot when queue work is unresolved, but that is
not evidence of a deployed, timely erasure-queue alert.

The monitor emits only `OK` or `ALERT`; it never reports a user,
object, prefix, provider message or number of tasks. It alerts for `failed` or
unknown status, a pending task with an error, exhausted/invalid attempts,
missing or implausible timestamps, and pending tasks older than 20 minutes.
The local candidate treats cancellation as healthy only for the explicitly identified pre-upload
guards; cancelled deletion tasks and unrecognized cancellation reasons alert.
Adding a new legitimate cancelled guard requires reviewing this allowlist.
The local candidate adds `voice_sample_upload_guard`; the already installed
monitor still uses the earlier six-entry allowlist until separately deployed.
The first 15 minutes are the existing intentional grace period for a deferred
second pass that protects against late provider uploads; five extra minutes are
allowed for the sweeper. A missing table, source mismatch, database error,
malformed status or inaccessible settings also results in `ALERT`.

The CLI selects the configured PostgreSQL database using verified TLS, refuses
to run if the source's host, port and database differ from either configured API
or worker container, sets the transaction read-only and queries only queue
metadata. It inspects stopped containers too: the existing guarded backup can
stop them normally. Service availability is outside this metric's scope. The
Google publisher sends a binary metric every five minutes. The policy template
covers an unhealthy value or a signal missing for 25 minutes; neither the
service/timer and policy are now installed as described above. A healthy signal is
only a snapshot of known queued work: it cannot prove physical erasure or that
every necessary deletion was entered into the queue.

## Permissions and deployment boundaries

- Provision a dedicated database login restricted to SELECT on the queue
  columns required by this check, and a private configuration containing only
  its database connection and TLS settings. Do not reuse broad application
  credentials when a limited login is possible.
- Current source-binding verification uses Docker inspect. Docker daemon
  access is effectively broad host control even when used only for inspection,
  and inspect returns container environment values to the process. Before
  deployment, evaluate replacing this with a trusted narrow binding service;
  never log the environment, DSN, user keys, paths or provider errors.
- The publisher needs Google Cloud Monitoring time-series write permission;
  the policy operator needs policy and notification-channel permissions. These
  permissions have not been granted as part of this work. The existing email
  notification channel is not proof this new alert reaches the recipient.
- A metric-absence policy does not trigger when no sample was ever ingested.
  Verify a first sample, then exercise both a synthetic unhealthy signal and
  cessation of the signal, including receipt by the intended channel, before
  relying on this control. See [Google's metric absence documentation](https://docs.cloud.google.com/monitoring/alerts/metric-absence).
- Expect at least the five-minute polling interval and provider evaluation
  delay; an outage of both the signal producer and its monitoring account is
  not independently covered. A normal queued operation can complete between
  checks, and immediate failed-task signals can be transient before a retry.

The [offline rehearsal](acceptance/privacy-witness-synthetic-2026-11-02/offline-restore-043e183d5fba478767026866154ee0ff.json)
tested the queue on disposable PostgreSQL: ordinary grace, stale pending,
retry exhaustion, failure, cancelled erasure versus a cancelled upload guard,
completion, and a read-only transaction. The run used network isolation and
removed its own resources. SQLite tests also exercised malformed settings,
source mismatch, no-detail error handling, and a simulated metric request.
It did not exercise a real monitoring policy, email delivery or production
database permissions.

## Read-only operating observations and installation plan

- Chrome showed `asb-free-test` uses `asb-pilot-backup` and a Cloud Platform
  OAuth scope. Its custom project role contains `monitoring.timeSeries.create`;
  reuse of that permission for this new metric is plausible but its first
  descriptor creation and write have not been tested. No role was added.
- Chrome showed the existing backup email channel configured to the previously
  approved address. It has not yet received an alert from this new policy.
- A read-only Neon SQL aggregation of the `storybook` database showed 12
  `account_deletion` tasks in `done` and no other queue statuses at that moment.
  This did not independently verify which database both VM containers use.
- `build_privacy_purge_monitor_bundle.py` creates a new owner-only local
  candidate with a per-file SHA-256 manifest; it excludes runtime configuration
  and common key-file extensions, rejects source symlinks and refuses to replace
  an existing destination. It does not install or start anything. The service
  template points to a separate `/opt/ai-story-book/privacy-purge-monitor/current`
  path and reuses the existing API virtualenv, leaving the app and backup
  `current` paths unchanged. The exact target state, package hashes and venv
  dependencies must be checked on the VM before any installation.
- A safe installation sequence is: inspect the existing backup units, queue
  schema, DB/TLS source binding, CPU and disk headroom without logging secrets;
  verify a locally built bundle and its manifest; stage it under a fresh
  monitor-only directory; validate the unit and configured inputs without
  changing the existing timer or restarting API, worker, proxy or backup;
  then start only the new monitor and verify its first real metric.
- Test email and the missing-signal policy with a separate synthetic metric and
  temporary, owned policy on the already approved channel. Do not create fake
  deletion tasks in the production database or alter the existing backup
  policy. Verify receipt and policy expiry; remove only the test policy. Metric
  data retention and possible Cloud Monitoring charges remain provider-governed.
- Before enabling the real policy, prove source binding during a simulated
  backup stop, confirm valid cancelled upload guards do not alert and cancelled
  actual erasures do, and prove an actual source mismatch or unreadable queue
  sends an unhealthy signal. Never mask a sustained failure as maintenance.
- Rollback is limited to disabling/stopping the new monitor unit and its new
  policy, removing only files this installation created after ownership checks,
  and keeping the existing backup alert, user data and runtime untouched. If a
  signal has previously been published, disabling only the timer can itself
  generate a missing-signal alert; coordinate disabling the new policy first.

During initial preparation the computer-use security review rejected a test
opening a local `file:` URL, so the proposed temporary-file handoff to Chrome
was not used or circumvented. The operator later completed normal CLI
authentication, allowing the installation documented above.

## Installer and operator commands

`scripts/manage_privacy_purge_monitor.py` is an isolated installer and
disabler for the pilot VM. It changes no application, worker, backup, policy,
credential, or database data. It requires explicit `--execute`, root, Google
instance metadata identifying project `gen-lang-client-0308507618` and VM
`asb-free-test`, an exact independently checked bundle-manifest SHA-256,
root-owned bundle files, private existing configuration, no existing monitor
installation or unit collision, and a successful read-only queue/source check.
It copies the bundle under a new monitor-only directory, verifies its contents,
creates only the two new systemd units, checks unit syntax, publishes one
signal and starts the new timer. A successful signal is provider write
acceptance, not proof of notification delivery. Installation of this timer
does **not** create an alert policy or prove that an email was received.

Prepare a fresh bundle with `build_privacy_purge_monitor_bundle.py` and retain
the exact SHA-256 of its `manifest.json` from a trusted local review. Transfer
that bundle and the manager script using the approved authenticated VM access
to a freshly created directory owned by the operator. As root, copy only that
owned directory into a new root-owned private staging directory; do not copy
existing application directories or change their ownership. Independently
compare the transferred manifest digest with the retained trusted digest.
The staged bundle and manager must be root-owned, with no group/world write.
Supply the root-owned, owner-only existing private file
`/etc/ai-story-book/pilot/private/privacy-purge-watch.env` with precisely
these two plain assignments pointing to already provisioned files:

```text
ASB_PURGE_MONITOR_ENV_FILE=/absolute/path/to/monitor-db.env
ASB_PURGE_MONITOR_CA_FILE=/absolute/path/to/database-ca.pem
```

The database configuration is owner-only, contains a narrowly scoped
read-only PostgreSQL connection and `DATABASE_SSL_MODE=verify-full`; the CA
file must also be root-owned and not group/world writable. The checker
compares the connection target to both existing API and worker containers.
Docker inspection carries broad host privileges; root is required and a
dedicated least-privilege service is a future improvement. The unit uses the
existing API virtualenv and fails the precheck if it is unavailable.

After the operator has verified and staged those inputs, the complete
installation is this single command on the specified VM. Substitute only the
trusted, non-secret digest and the path to the root-owned bundle:

```sh
sudo python3 /absolute/root-owned/staging/manage_privacy_purge_monitor.py install --execute --bundle /absolute/root-owned/staging/bundle --manifest-sha256 TRUSTED_MANIFEST_SHA256
```

On any failure the output is intentionally generic to avoid disclosing
connection information. An interrupted or failed install can leave the new
monitor-only directory or units in place; do not retry over them. Review the
new unit journal privately and use the rollback command below. The tool never
automatically deletes a partial directory, and refuses to touch changed unit
files. The unit can have been enabled if an error occurred during activation,
so a failed install must not be assumed inactive.

Use the separate alert-policy template and the already approved email channel
only after a first metric exists and a separate synthetic unhealthy and absent
signal have demonstrated actual email delivery. Those policy and notification
actions remain manual/unverified. To disable this monitor safely, first disable
**only its own** Cloud Monitoring policy, verify it is disabled, and then run:

```sh
sudo python3 /absolute/root-owned/staging/manage_privacy_purge_monitor.py rollback --execute --policy-disabled
```

`--policy-disabled` is an operator attestation, not an automated cloud-policy
check. The rollback verifies the installation receipt and unit digests, then
disables/stops only the new timer and service. It deliberately retains files
for inspection and never removes the backup policy or monitor data; any
subsequent cleanup or reinstallation requires separate ownership review.
The installer has executed once successfully on the VM; rollback and the
synthetic monitoring and notification scenarios await integrated verification.
