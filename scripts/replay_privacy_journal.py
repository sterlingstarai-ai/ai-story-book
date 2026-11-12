"""Conservative replay prototype for an independently isolated restore target.

Never call against an active database or storage bucket. No CLI or deployment
entry point is provided: journal coverage, ordering, independent durability,
concurrent changes and target isolation are not yet established. Success never
authorizes opening the restored system. Reruns are required after failures.
"""

from collections import defaultdict
import json
import os
import re
from urllib.parse import urlsplit

from sqlalchemy import delete, select, text, update

from src.services.privacy_journal import (
    RESOURCE_ACTIONS, JournalEntry, JournalScan, consent_state_from_payload, consent_state_to_payload,
    credential_state_from_payload, credential_state_to_payload,
    deletion_receipt_from_payload, deletion_receipt_to_payload,
)


class ReplayIncomplete(RuntimeError):
    """Replay failed or needs manual follow-up; keep target quarantined."""


_USER_KEY = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_EVENT_ID = re.compile(r'^[0-9a-f]{32}$')
_ACTIONS = {'account_delete', 'consent_revoke', 'consent_grant', 'photo_revoke', 'credential_revoke'} | RESOURCE_ACTIONS
_MAX_PURGE_LIST_KEYS = 100000


def encode_replay_transfer(scan, journal_sha256, legacy_public_url):
    """Encode an already authenticated scan for private sandbox stdin."""
    events = []
    for entry in scan.committed:
        item = {'id': entry.event_id, 'action': entry.action, 'subject': entry.subject,
                'revision': entry.revision, 'credential_state': credential_state_to_payload(entry.credential_state)}
        for key, value in (
            ('resource_id', entry.resource_id), ('consent_state', consent_state_to_payload(entry.consent_state)),
            ('deletion_receipt', deletion_receipt_to_payload(entry.deletion_receipt)),
        ):
            if value is not None:
                item[key] = value
        events.append(item)
    return json.dumps({'events': events, 'journal_sha256': journal_sha256,
                       'legacy_public_url': legacy_public_url}, separators=(',', ':')).encode()


async def _require_disposable_fixture(db):
    """Do not permit this unfinished replayer to mutate a real target."""
    from src.core.config import settings

    if os.environ.get('TESTING', '').lower() != 'true':
        raise ReplayIncomplete('Only disposable test targets are supported')
    url = db.get_bind().url
    if url.drivername == 'sqlite+aiosqlite' and url.database == f'./test_{os.getpid()}.db':
        return
    endpoint = urlsplit(settings.s3_endpoint)
    if not (url.drivername == 'postgresql+asyncpg' and url.host == '127.0.0.1'
            and url.username == 'runtime_test' and url.password == 'disposable-runtime-password'
            and url.database == 'runtime_test' and endpoint.scheme == 'http'
            and endpoint.hostname == '127.0.0.1' and settings.s3_bucket == 'restore-rehearsal'):
        raise ReplayIncomplete('Only disposable test targets are supported')
    token = os.environ.get('ASB_DISPOSABLE_REPLAY_TOKEN', '')
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise ReplayIncomplete('Disposable fixture marker is missing')
    try:
        marked_endpoint = await db.scalar(text(
            'SELECT s3_endpoint FROM public.asb_disposable_fixture_guard WHERE token=:token'
        ), {'token': token})
    except Exception:
        raise ReplayIncomplete('Disposable fixture marker is missing') from None
    if marked_endpoint != settings.s3_endpoint:
        raise ReplayIncomplete('Disposable fixture marker does not match storage target')


async def _verify_completed_purges(db):
    """Read back known completed targets; never certify unknown or versioned objects."""
    from src.core.config import settings
    from src.models.db import StoragePurgeTask
    from src.services.storage import _call_s3, _validated_prefix_objects, get_s3_client

    tasks = list((await db.scalars(select(StoragePurgeTask).where(StoragePurgeTask.status == 'done'))).all())
    if not tasks:
        return
    try:
        client = get_s3_client()
        versioning = await _call_s3(client.get_bucket_versioning, Bucket=settings.s3_bucket)
        if not isinstance(versioning, dict) or 'Status' in versioning:
            raise ReplayIncomplete('Versioned storage cannot be verified; target must remain isolated')
        for task in tasks:
            if task.kind not in ('keys', 'prefix') or not isinstance(task.target, str) or not task.target:
                raise ReplayIncomplete('Storage deletion target is invalid; target must remain isolated')
            token = None
            seen_tokens = set()
            seen_keys = set()
            page_count = 0
            while True:
                page_count += 1
                if page_count > 10000:
                    raise ValueError('listing page limit exceeded')
                args = {'Bucket': settings.s3_bucket, 'Prefix': task.target}
                if token is not None:
                    args['ContinuationToken'] = token
                page = await _call_s3(client.list_objects_v2, **args)
                # Use the same fail-closed page validation as live purge.
                # In particular a count mismatch or unexpected CommonPrefixes
                # must not be interpreted as proof that a prefix is empty.
                objects = _validated_prefix_objects(page, task.target)
                keys = {obj['Key'] for obj in objects}
                if keys & seen_keys:
                    raise ValueError('duplicate object across listing pages')
                if len(seen_keys) + len(keys) > _MAX_PURGE_LIST_KEYS:
                    raise ValueError('listing key limit exceeded')
                seen_keys.update(keys)
                if any(task.kind == 'prefix' or obj['Key'] == task.target for obj in objects):
                    raise ReplayIncomplete('Deleted storage object remains; target must remain isolated')
                if not page['IsTruncated']:
                    if 'NextContinuationToken' in page:
                        raise ValueError('inconsistent final listing page')
                    break
                token = page.get('NextContinuationToken')
                if (not isinstance(token, str) or not token or token in seen_tokens
                        or len(seen_tokens) >= 10000):
                    raise ValueError('invalid continuation')
                seen_tokens.add(token)
    except ReplayIncomplete:
        raise
    except Exception:
        # Provider exceptions can include object names, URLs and credentials.
        raise ReplayIncomplete('Storage deletion could not be verified; target must remain isolated') from None


def _validated_journal_events(scan: JournalScan):
    """Validate event shape and per-subject ordering without mutating any target."""
    if not isinstance(scan, JournalScan) or scan.restore_authorized is not False or type(scan.pending_count) is not int or scan.pending_count != 0:
        raise ReplayIncomplete('Journal scan is incomplete; target must remain isolated')
    events = defaultdict(list)
    revisions = defaultdict(list)
    ids = set()
    for entry in scan.committed:
        if (not isinstance(entry, JournalEntry) or not isinstance(entry.event_id, str)
                or not _EVENT_ID.fullmatch(entry.event_id) or entry.event_id in ids
                or not isinstance(entry.action, str) or entry.action not in _ACTIONS
                or not isinstance(entry.subject, str) or not _USER_KEY.fullmatch(entry.subject)
                or type(entry.revision) is not int or not 1 <= entry.revision <= 2**63 - 1):
            raise ReplayIncomplete('Journal event is invalid; target must remain isolated')
        try:
            if entry.credential_state is not None and entry.action != 'credential_revoke':
                raise ValueError('invalid credential action')
            valid_resource = isinstance(entry.resource_id, str) and bool(re.fullmatch('[A-Za-z0-9_-]{1,60}', entry.resource_id))
            if (entry.action in RESOURCE_ACTIONS) != valid_resource or (entry.action not in RESOURCE_ACTIONS and entry.resource_id is not None):
                raise ValueError('invalid resource')
            if (entry.action == 'consent_grant') != (consent_state_to_payload(entry.consent_state) is not None):
                raise ValueError('invalid consent state')
            credential_state_to_payload(entry.credential_state)
            receipt = deletion_receipt_to_payload(entry.deletion_receipt)
            if receipt is not None and entry.action != 'book_delete':
                raise ValueError('invalid deletion receipt')
        except Exception:
            raise ReplayIncomplete('Journal event is invalid; target must remain isolated') from None
        ids.add(entry.event_id)
        events[entry.subject].append(entry)
        revisions[entry.subject].append(entry.revision)

    for values in revisions.values():
        # This fixture requires the complete history from revision 1. A
        # production restore also needs an authenticated checkpoint and an
        # external completeness watermark; a contiguous prefix is insufficient.
        if sorted(values) != list(range(1, len(values) + 1)):
            raise ReplayIncomplete('Journal revisions are incomplete; target must remain isolated')

    for entries in events.values():
        entries.sort(key=lambda item: item.revision)
        requests = [entry.deletion_receipt.request_id for entry in entries if entry.deletion_receipt is not None]
        if len(requests) != len(set(requests)):
            raise ReplayIncomplete('Journal deletion requests conflict; target must remain isolated')
        deleted_profiles = set()
        for entry in entries:
            if entry.action == 'profile_delete':
                deleted_profiles.add(entry.resource_id)
            if entry.deletion_receipt is not None and entry.deletion_receipt.profile_id in deleted_profiles:
                raise ReplayIncomplete('Journal deletion profile is invalid; target must remain isolated')

    # A deleted account identity is a permanent tombstone. Later revocations
    # may be retried, but an active consent or credential state after deletion
    # must never be replayed into that tombstone. Validate the complete scan
    # before applying even the first event, including history already present
    # in a backup, so an inconsistent record cannot leave a partial replay.
    for entries in events.values():
        deleted = False
        for entry in entries:
            if entry.action == 'account_delete':
                deleted = True
            elif deleted and entry.action == 'consent_grant':
                raise ReplayIncomplete('Deleted account has a later consent grant; target must remain isolated')
            elif deleted and entry.action == 'voice_changed':
                raise ReplayIncomplete('Deleted account has a later voice change; target must remain isolated')
            elif deleted and entry.action == 'credential_revoke' and entry.credential_state is not None:
                state = entry.credential_state
                if any(value is not None for value in (
                    state.device_hash, state.recovery_hash, state.previous_hash, state.recovery_created_at,
                )):
                    raise ReplayIncomplete('Deleted account has later credentials; target must remain isolated')

    return events, ids


def plan_quarantined_replay(scan: JournalScan) -> dict:
    """Validate structure only; independent latest history remains unproven."""
    events, ids = _validated_journal_events(scan)
    return {'status': 'JOURNAL_STRUCTURE_VALIDATED', 'subject_count': len(events),
            'event_count': len(ids), 'latest_head_verified': False,
            'privacy_replay_authorized': False, 'restore_authorized': False}


async def _apply_replay_core(db, scan: JournalScan, *, backup_marker=None, sandbox_token=None) -> dict:
    """Shared mutation implementation, presently restricted to disposable targets.

    This internal entry point deliberately enforces the fixture check itself:
    merely importing or calling it cannot turn a production target into a test.
    Future production support requires a reviewed concrete target/evidence
    verifier, not a caller-supplied predicate or a boolean authorization flag.
    """
    events, ids = _validated_journal_events(scan)
    if sandbox_token is None:
        await _require_disposable_fixture(db)
    else:
        from quarantined_replay_preflight import verify_replay_destination
        await verify_replay_destination(db, sandbox_token)

    # The journal cannot reconstruct an active voice. A later explicit erasure
    # of the same voice or account makes the earlier change unnecessary.
    for entries in events.values():
        erased_voices = set()
        erased_account = False
        for entry in reversed(entries):
            if entry.action == 'account_delete':
                erased_account = True
            elif entry.action in {'voice_delete', 'voice_revoke'}:
                erased_voices.add(entry.resource_id)
            elif (entry.action == 'voice_changed' and not erased_account
                  and entry.resource_id not in erased_voices):
                raise ReplayIncomplete('Voice state requires verified recovery; target must remain isolated')

    if backup_marker is not None:
        # The caller must have separately verified the marker's source. This
        # proves the backup boundary only, never latest-history completeness.
        from src.services.privacy_journal_verify import verify_backup_checkpoint
        try:
            await verify_backup_checkpoint(db, scan, backup_marker)
        except Exception:
            raise ReplayIncomplete('Backup checkpoint is invalid; target must remain isolated') from None

    # Imports are delayed so journal parsing alone never initializes a DB or
    # storage client. The existing deletion helpers remain the only data path.
    from src.core.utils import utcnow
    from src.models.db import (AccountIdentity, Book, BookDeletionReceipt, BookShare, Character, ChildProfile, Job, PrivacyJournalOutbox,
                               StoragePurgeTask, UserConsent, VoiceProfile)
    from src.routers.characters import delete_character
    from src.routers.consent import ConsentGrantRequest, grant_consent, purge_photo_derived_data, revoke_consent
    from src.routers.library import delete_book
    from src.routers.profiles import delete_profile
    from src.routers.shares import revoke_share
    from src.routers.users import _delete_user_data
    from src.routers.voice_profiles import delete_voice_profile, revoke_voice_profile_consent
    from src.services.storage import key_from_public_url, voice_sample_prefix

    resource_handlers = {
        'book_delete': (Book, delete_book),
        'character_delete': (Character, delete_character),
        'profile_delete': (ChildProfile, delete_profile),
        'voice_delete': (VoiceProfile, delete_voice_profile),
        'voice_revoke': (VoiceProfile, revoke_voice_profile_consent),
        'share_revoke': (Book, revoke_share),
    }

    async def tombstone(session, user_key):
        identity = await session.get(AccountIdentity, user_key)
        if identity is None:
            session.add(AccountIdentity(user_key=user_key, deleted=True))
        else:
            identity.deleted = True
            identity.device_key_hash = None
            identity.recovery_code_hash = None
            identity.previous_recovery_code_hash = None
            identity.recovery_code_created_at = None
            identity.updated_at = utcnow()
        await session.flush()

    async def verify_tombstone(session, user_key):
        identity = await session.get(AccountIdentity, user_key)
        if identity is None or not identity.deleted:
            raise ReplayIncomplete('Deleted account is not tombstoned; target must remain isolated')
        # Production deletion retains the device hash solely for a safe
        # lost-response retry; deleted identities are rejected at auth. Recovery
        # hashes and their creation time must still be cleared.
        if any(value is not None for value in (
            identity.recovery_code_hash, identity.previous_recovery_code_hash,
            identity.recovery_code_created_at,
        )):
            raise ReplayIncomplete('Deleted account still has credentials; target must remain isolated')
        for table in AccountIdentity.metadata.sorted_tables:
            if 'user_key' not in table.c or table.name in {
                'account_identities', 'storage_purge_tasks', 'privacy_journal_outbox',
            }:
                continue
            if await session.scalar(select(1).select_from(table).where(table.c.user_key == user_key).limit(1)):
                raise ReplayIncomplete('Deleted account still has rows; target must remain isolated')

    async def verify_recorded_state(session, user_key, ordered, *, stage):
        if any(entry.action == 'account_delete' for entry in ordered):
            await verify_tombstone(session, user_key)
            return

        # Compare only state whose last change is represented by this history.
        # Missing history still cannot be proven from this local comparison.
        consent_expected = None
        for entry in ordered:
            if entry.action == 'consent_revoke':
                consent_expected = ('revoked', None, False)
            elif entry.action == 'consent_grant':
                consent_expected = ('grant', entry.consent_state, entry.consent_state.photos)
            elif entry.action == 'photo_revoke':
                if consent_expected is None:
                    consent_expected = ('photo_only', None, False)
                else:
                    consent_expected = (consent_expected[0], consent_expected[1], False)
        if consent_expected is not None:
            active = list((await session.scalars(select(UserConsent).where(
                UserConsent.user_key == user_key, UserConsent.revoked_at.is_(None),
            ))).all())
            kind, consent, photos = consent_expected
            invalid = (kind == 'revoked' and bool(active)) or (
                kind == 'photo_only' and any(row.photos for row in active)
            )
            if kind == 'grant':
                invalid = len(active) != 1 or (
                    active[0].privacy != consent.privacy or active[0].photos != photos
                    or active[0].data_processing != consent.data_processing
                    or active[0].granted != (consent.privacy and consent.data_processing)
                    or active[0].consent_version != consent.version
                )
            if invalid:
                raise ReplayIncomplete(f'Consent {stage} state disagrees; target must remain isolated')
            photo_permission = photos and (kind != 'grant' or (consent.privacy and consent.data_processing))
            if not photo_permission:
                # A missing purge intent cannot prove that photo-derived data
                # was erased. Match the canonical consent purge's two durable
                # provenance flags, even for events already included in H0.
                # A later grant with all three permissions supersedes this
                # current-state check; historical consent generation is not
                # attested by these provenance flags.
                remaining = await session.execute(select(
                    select(Character.id).where(Character.user_key == user_key,
                        Character.from_photo.is_(True)).exists(),
                    select(Job.id).where(Job.user_key == user_key,
                        Job.photo_derived.is_(True)).exists(),
                ))
                if any(remaining.one()):
                    raise ReplayIncomplete(f'Photo-derived {stage} state disagrees; target must remain isolated')

        credential_entries = [entry for entry in ordered if entry.action == 'credential_revoke']
        if credential_entries:
            identity = await session.get(AccountIdentity, user_key)
            state = credential_entries[-1].credential_state
            expected = ((state.device_hash, state.recovery_hash, state.previous_hash, state.recovery_created_at)
                        if state is not None else (None, None, None, None))
            if (identity is None or identity.deleted or (
                identity.device_key_hash, identity.recovery_code_hash,
                identity.previous_recovery_code_hash, identity.recovery_code_created_at,
            ) != expected):
                raise ReplayIncomplete(f'Credential {stage} state disagrees; target must remain isolated')

        deleted_models = {
            'book_delete': Book, 'character_delete': Character,
            'profile_delete': ChildProfile, 'voice_delete': VoiceProfile,
        }
        profile_deletions = {entry.resource_id: entry.revision for entry in ordered
                             if entry.action == 'profile_delete'}
        for entry in ordered:
            if entry.action in deleted_models:
                if await session.get(deleted_models[entry.action], entry.resource_id) is not None:
                    raise ReplayIncomplete(f'Resource {stage} state disagrees; target must remain isolated')
            elif entry.action == 'voice_revoke':
                voice = await session.get(VoiceProfile, entry.resource_id)
                if voice is not None and (voice.user_key != user_key or voice.consented or voice.active
                                          or voice.sample_audio_url or voice.provider_voice_id):
                    raise ReplayIncomplete(f'Voice {stage} state disagrees; target must remain isolated')
            elif entry.action == 'share_revoke':
                # Later share creation is not journaled yet, so an active link
                # cannot be distinguished safely from a missed withdrawal.
                book = await session.get(Book, entry.resource_id)
                if book is not None and book.user_key != user_key:
                    raise ReplayIncomplete('Resource ownership mismatch; target must remain isolated')
                active_share = await session.scalar(select(BookShare.id).where(
                    BookShare.book_id == entry.resource_id, BookShare.user_key == user_key,
                    BookShare.revoked_at.is_(None),
                ).limit(1))
                if active_share is not None:
                    raise ReplayIncomplete(f'Share {stage} state disagrees; target must remain isolated')
            if entry.deletion_receipt is not None:
                info = entry.deletion_receipt
                removed_profile = profile_deletions.get(info.profile_id, 0) > entry.revision
                receipt = await session.get(BookDeletionReceipt, (user_key, info.request_id))
                if ((removed_profile and receipt is not None) or (not removed_profile and (
                    receipt is None or receipt.book_id != entry.resource_id or receipt.profile_id != info.profile_id
                ))):
                    raise ReplayIncomplete(f'Deletion receipt {stage} state disagrees; target must remain isolated')
                if not removed_profile and info.profile_id is not None:
                    profile = await session.get(ChildProfile, info.profile_id)
                    if profile is None or profile.user_key != user_key:
                        raise ReplayIncomplete(f'Deletion receipt {stage} profile disagrees; target must remain isolated')

    async def verify_purge_queue(session):
        outstanding = await session.scalar(select(StoragePurgeTask.id).where(
            StoragePurgeTask.status.not_in(('done', 'cancelled')),
        ).limit(1))
        if outstanding is not None:
            raise ReplayIncomplete('Storage deletion is incomplete; target must remain isolated')
        await _verify_completed_purges(session)

    def require_owned_voice_media(subject, url):
        if url:
            key = key_from_public_url(url)
            if not key or not key.startswith((voice_sample_prefix(subject), f'voice-samples/{subject}/')):
                raise ReplayIncomplete('Voice media cannot be located safely; target must remain isolated')

    try:
        # Validate every checkpoint before changing any target data. The
        # complete external history and its high-water mark are still unproved.
        checkpoints = {}
        checkpoint_revisions = defaultdict(list)
        expected_by_id = {entry.event_id: entry for entries in events.values() for entry in entries}
        all_checkpoint_rows = list((await db.scalars(select(PrivacyJournalOutbox))).all())
        for row in all_checkpoint_rows:
            entry = expected_by_id.get(row.event_id)
            if (entry is None or entry.subject != row.user_key or entry.revision != row.revision
                    or entry.action != row.action
                    or entry.credential_state != credential_state_from_payload(row.credential_state)
                    or entry.resource_id != row.resource_id
                    or entry.consent_state != consent_state_from_payload(row.consent_state)
                    or entry.deletion_receipt != deletion_receipt_from_payload(row.deletion_receipt)):
                raise ReplayIncomplete('Backup checkpoint disagrees with journal; target must remain isolated')
            checkpoint_revisions[row.user_key].append(row.revision)
        for subject in events:
            versions = sorted(checkpoint_revisions.get(subject, ()))
            if versions != list(range(1, len(versions) + 1)):
                raise ReplayIncomplete('Backup checkpoint is incomplete; target must remain isolated')
            checkpoints[subject] = len(versions)

        # Ownership mismatches anywhere in the scan must be detected before
        # committing changes to even an unrelated subject. Recheck during
        # application as well; neither check proves continuous isolation.
        for subject, entries in events.items():
            if any(entry.action == 'account_delete' and entry.revision > checkpoints[subject] for entry in entries):
                samples = await db.scalars(select(VoiceProfile.sample_audio_url).where(
                    VoiceProfile.user_key == subject))
                for url in samples:
                    require_owned_voice_media(subject, url)
            for entry in entries:
                if entry.action in RESOURCE_ACTIONS:
                    model = VoiceProfile if entry.action == 'voice_changed' else resource_handlers[entry.action][0]
                    resource = await db.get(model, entry.resource_id)
                    if resource is not None and resource.user_key != subject:
                        raise ReplayIncomplete('Resource ownership mismatch; target must remain isolated')
                    if (entry.action in {'voice_delete', 'voice_revoke'}
                            and entry.revision > checkpoints[subject]
                            and resource is not None):
                        require_owned_voice_media(subject, resource.sample_audio_url)
                if entry.deletion_receipt is not None:
                    info = entry.deletion_receipt
                    receipt = await db.get(BookDeletionReceipt, (subject, info.request_id))
                    if receipt is not None and (receipt.book_id != entry.resource_id or receipt.profile_id != info.profile_id):
                        raise ReplayIncomplete('Deletion receipt conflicts; target must remain isolated')

        # A matching event in a backup does not itself prove its effects are
        # present in the database. Reject inconsistent deletion checkpoints
        # before committing any unrelated subject's replay.
        for subject, entries in events.items():
            await verify_recorded_state(db, subject,
                [entry for entry in entries if entry.revision <= checkpoints[subject]], stage='checkpoint')

        # An existing failed or incomplete erasure anywhere in the backup,
        # including an unknown owner, blocks all replay before any commit.
        # Completed targets are read back now and again after replay.
        await verify_purge_queue(db)

        applied = 0
        for subject, entries in events.items():
            for entry in entries:
                if entry.revision <= checkpoints[subject]:
                    continue
                if entry.action == 'account_delete':
                    identity = await db.get(AccountIdentity, subject)
                    if identity is not None and identity.deleted:
                        # A retry may skip normal erasure only when every modeled
                        # user-owned table is empty for the deleted account.
                        for table in AccountIdentity.metadata.sorted_tables:
                            if 'user_key' not in table.c or table.name in {
                                'account_identities', 'storage_purge_tasks', 'privacy_journal_outbox',
                            }:
                                continue
                            if await db.scalar(select(1).select_from(table).where(table.c.user_key == subject).limit(1)):
                                raise ReplayIncomplete('Deleted account still has rows; target must remain isolated')
                        await tombstone(db, subject)
                        await db.commit()
                    else:
                        result = await _delete_user_data(db, subject, tombstone)
                        if result.get('purge_retry_pending'):
                            raise ReplayIncomplete('Storage deletion is incomplete; target must remain isolated')
                elif entry.action == 'consent_revoke':
                    await revoke_consent(db=db, user_key=subject)
                elif entry.action == 'consent_grant':
                    consent = entry.consent_state
                    await grant_consent(ConsentGrantRequest(privacy=consent.privacy, photos=consent.photos,
                        data_processing=consent.data_processing, consent_version=consent.version),
                        db=db, user_key=subject)
                elif entry.action == 'photo_revoke':
                    await db.execute(update(UserConsent).where(
                        UserConsent.user_key == subject, UserConsent.revoked_at.is_(None),
                    ).values(photos=False))
                    failed = await purge_photo_derived_data(db, subject, reason='restore_photo_revoke')
                    if failed:
                        raise ReplayIncomplete('Storage deletion is incomplete; target must remain isolated')
                elif entry.action == 'credential_revoke':
                    identity = await db.get(AccountIdentity, subject)
                    if identity is None:
                        identity = AccountIdentity(user_key=subject, deleted=False)
                        db.add(identity)
                    state = entry.credential_state
                    identity.device_key_hash = state.device_hash if state else None
                    identity.recovery_code_hash = state.recovery_hash if state else None
                    identity.previous_recovery_code_hash = state.previous_hash if state else None
                    identity.recovery_code_created_at = state.recovery_created_at if state else None
                    identity.updated_at = utcnow()
                    await db.commit()
                elif entry.action in RESOURCE_ACTIONS and entry.action != 'voice_changed':
                    model, handler = resource_handlers[entry.action]
                    resource = await db.get(model, entry.resource_id)
                    if resource is not None:
                        if resource.user_key != subject:
                            raise ReplayIncomplete('Resource ownership mismatch; target must remain isolated')
                        if entry.action == 'book_delete':
                            result = await handler(entry.resource_id, db=db, user_key=subject, profile_id=None)
                        else:
                            result = await handler(entry.resource_id, db=db, user_key=subject)
                        if result.get('purge_retry_pending'):
                            raise ReplayIncomplete('Storage deletion is incomplete; target must remain isolated')
                    if entry.deletion_receipt is not None:
                        info = entry.deletion_receipt
                        existing = await db.get(BookDeletionReceipt, (subject, info.request_id))
                        if existing is not None and (
                            existing.book_id != entry.resource_id or existing.profile_id != info.profile_id
                        ):
                            raise ReplayIncomplete('Deletion receipt conflicts; target must remain isolated')
                        if existing is None:
                            db.add(BookDeletionReceipt(user_key=subject, request_id=info.request_id,
                                book_id=entry.resource_id, profile_id=info.profile_id))
                    if entry.action == 'profile_delete' and resource is None:
                        # Profile may already be absent in the restored copy;
                        # its scoped receipt evidence must not survive deletion.
                        await db.execute(delete(BookDeletionReceipt).where(
                            BookDeletionReceipt.user_key == subject,
                            BookDeletionReceipt.profile_id == entry.resource_id,
                        ))
                outstanding = await db.scalar(select(StoragePurgeTask.id).where(
                    StoragePurgeTask.user_key == subject,
                    StoragePurgeTask.status.not_in(('done', 'cancelled')),
                ).limit(1))
                if outstanding is not None:
                    raise ReplayIncomplete('Storage deletion is incomplete; target must remain isolated')
                # A crash before this checkpoint causes a conservative replay;
                # it never releases the target or silently skips an event.
                db.add(PrivacyJournalOutbox(event_id=entry.event_id, user_key=subject,
                    revision=entry.revision, action=entry.action, published_at=utcnow(),
                    credential_state=credential_state_to_payload(entry.credential_state), resource_id=entry.resource_id,
                    consent_state=consent_state_to_payload(entry.consent_state),
                    deletion_receipt=deletion_receipt_to_payload(entry.deletion_receipt)))
                await db.commit()
                applied += 1
            # Even if all events were in the backup, unresolved storage work
            # prevents declaring this fixture replay complete.
            outstanding = await db.scalar(select(StoragePurgeTask.id).where(
                StoragePurgeTask.user_key == subject,
                StoragePurgeTask.status.not_in(('done', 'cancelled')),
            ).limit(1))
            if outstanding is not None:
                raise ReplayIncomplete('Storage deletion is incomplete; target must remain isolated')
            await verify_recorded_state(db, subject, entries, stage='replay')
        # A restored backup may also contain older purge work with no journal
        # subject, including tasks whose owner is unknown. Checking only the
        # subjects in the scan would silently miss those tasks (or all tasks
        # when the scan is empty), and could report a misleading clean replay.
        await verify_purge_queue(db)
        return {'status': 'REPLAYED_STILL_QUARANTINED', 'subject_count': len(events),
                'event_count': len(ids), 'applied_count': applied,
                # Later voice re-consent and replacement samples are not in
                # the journal, so no scan can certify that voice recovery is
                # complete, even when it contains no voice revocation.
                'voice_state_recovery_supported': False, 'restore_authorized': False}
    except ReplayIncomplete:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise ReplayIncomplete('Replay failed; target must remain isolated') from None


async def replay_quarantined(db, scan: JournalScan, *, backup_marker=None) -> dict:
    """Apply conservative changes only to the existing disposable fixture."""
    return await _apply_replay_core(db, scan, backup_marker=backup_marker)


async def replay_isolated_production(db, scan: JournalScan, *, backup_marker=None) -> dict:
    """Reserve a production entry point without granting replay or publication.

    Authenticated latest-watermark verification, all-writer fencing, persistent
    target isolation and complete storage/auth/voice coverage do not yet have
    concrete production verifiers. Caller assertions are not evidence. Until
    those verifiers exist this operation fails before touching either target.
    """
    raise ReplayIncomplete('Production replay evidence is unavailable; target must remain isolated')
