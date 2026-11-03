"""Test mirrored create-only journal objects in two disposable local S3 stores."""
import os
import uuid
from urllib.parse import urlsplit

from run_restore_replay_fixture import require_local_fixture


def main():
    require_local_fixture()
    other = urlsplit(os.environ.get('ASB_SECOND_FIXTURE_S3', ''))
    first = urlsplit(os.environ['S3_ENDPOINT'])
    if (other.scheme != 'http' or other.hostname != '127.0.0.1' or not other.port
            or other.netloc == first.netloc or other.path not in ('', '/')):
        raise RuntimeError('A distinct disposable loopback storage target is required')
    import boto3
    from botocore.config import Config
    from src.services.privacy_journal import JournalError, PrivacyJournal
    from src.services.privacy_journal_backfill import backfill_fenced_journal
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore

    def client(endpoint):
        return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id='runtime_test',
            aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
            config=Config(signature_version='s3v4', s3={'addressing_style':'path'},
                          connect_timeout=5, read_timeout=10))
    a, b = client(os.environ['S3_ENDPOINT']), client(os.environ['ASB_SECOND_FIXTURE_S3'])
    bucket = 'restore-rehearsal'
    first_store, second_store = S3ImmutableJournalStore(a, bucket), S3ImmutableJournalStore(b, bucket)
    journal = PrivacyJournal(MirroredJournalStore(first_store, second_store), b'k' * 32)
    events = []
    try:
        source = PrivacyJournal(first_store, b'k' * 32)
        event = source.begin('consent_revoke', '00000000-0000-4000-8000-000000000077', revision=1)
        events.append(event)
        source.commit(event)
        for _ in (1, 2):
            result = backfill_fenced_journal(first_store, second_store)
            if result != {'status': 'BACKFILL_MATCHES', 'object_count': 2, 'restore_authorized': False}:
                raise RuntimeError('Fixture journal backfill failed')
        later = journal.begin('account_delete', '00000000-0000-4000-8000-000000000077', revision=2)
        events.append(later)
        journal.commit(later)
        prefix = f'privacy-journal/v1/{event}/'
        intent, commit = prefix + 'intent', prefix + 'commit'
        original = first_store.read(intent)
        try:
            first_store.create(intent, b'overwrite-attempt')
        except JournalError:
            pass
        else:
            raise RuntimeError('Fixture provider did not enforce create-only writes')
        if first_store.read(intent) != original or len(journal.scan().committed) != 2:
            raise RuntimeError('Fixture journal integrity check failed')
        b.delete_object(Bucket=bucket, Key=commit)
        try:
            journal.scan()
        except JournalError:
            pass
        else:
            raise RuntimeError('Missing fixture witness record was accepted')
        second_store.create(commit, first_store.read(commit))
        if len(journal.scan().committed) != 2:
            raise RuntimeError('Fixture journal retry did not recover')

        class FaultInjectedStore:
            def __init__(self, delegate):
                self.delegate = delegate
                self.fail_writes = False

            def create(self, name, data):
                if self.fail_writes:
                    raise RuntimeError('synthetic witness outage')
                return self.delegate.create(name, data)

            def read(self, name):
                return self.delegate.read(name)

            def list_names(self, prefix):
                return self.delegate.list_names(prefix)

        witness = FaultInjectedStore(second_store)
        retrier = PrivacyJournal(MirroredJournalStore(first_store, witness), b'k' * 32)
        partial = uuid.uuid4().hex
        events.append(partial)
        subject = '00000000-0000-4000-8000-000000000077'
        witness.fail_writes = True
        try:
            retrier.begin('consent_revoke', subject, revision=3, event_id=partial)
        except JournalError:
            pass
        else:
            raise RuntimeError('A partial intent was incorrectly reported as replicated')
        partial_intent = f'privacy-journal/v1/{partial}/intent'
        original_intent = first_store.read(partial_intent)
        witness.fail_writes = False
        retrier.begin('consent_revoke', subject, revision=3, event_id=partial)
        if second_store.read(partial_intent) != original_intent:
            raise RuntimeError('Partial intent did not preserve original ciphertext')
        witness.fail_writes = True
        try:
            retrier.commit(partial)
        except JournalError:
            pass
        else:
            raise RuntimeError('A partial commit was incorrectly reported as replicated')
        partial_commit = f'privacy-journal/v1/{partial}/commit'
        original_commit = first_store.read(partial_commit)
        witness.fail_writes = False
        retrier.commit(partial)
        if second_store.read(partial_commit) != original_commit:
            raise RuntimeError('Partial commit did not preserve original ciphertext')

        conflict = uuid.uuid4().hex
        events.append(conflict)
        PrivacyJournal(first_store, b'k' * 32).begin('consent_revoke', subject, revision=4, event_id=conflict)
        PrivacyJournal(second_store, b'k' * 32).begin('account_delete', subject, revision=4, event_id=conflict)
        conflict_name = f'privacy-journal/v1/{conflict}/intent'
        a_before, b_before = first_store.read(conflict_name), second_store.read(conflict_name)
        try:
            retrier.begin('consent_revoke', subject, revision=4, event_id=conflict)
        except JournalError:
            pass
        else:
            raise RuntimeError('Conflicting witness content was incorrectly accepted')
        if first_store.read(conflict_name) != a_before or second_store.read(conflict_name) != b_before:
            raise RuntimeError('Conflicting witness content was overwritten')
        print('Two disposable S3 stores verified partial write repair and refused conflicting ciphertext')
    finally:
        if events:
            for c in (a, b):
                for event_id in events:
                    for phase in ('intent', 'commit', 'abort'):
                        c.delete_object(Bucket=bucket, Key=f'privacy-journal/v1/{event_id}/{phase}')
        a.close()
        b.close()


if __name__ == '__main__':
    main()
