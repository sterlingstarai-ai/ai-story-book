"""Compare local candidate source trees to the current checkout without deployment."""
import argparse
import json
from pathlib import Path

from build_narration_candidate import checkout_hashes, ensure_local_daemon, source_hashes


SENSITIVE_PATHS = {
    'alembic/versions/8a34e19c6b72_book_deletion_receipts.py': 'book deletion receipt migration',
    'src/routers/library.py': 'book deletion event handling',
    'src/routers/characters.py': 'character deletion event handling',
    'src/routers/consent.py': 'consent decisions and photo purge status',
    'src/routers/profiles.py': 'profile deletion and receipt cleanup',
    'src/routers/users.py': 'account deletion and receipt cleanup',
    'src/routers/account.py': 'account media-scope endpoint',
    'src/models/dto.py': 'API response contract for account media scope',
    'src/models/db.py': 'narration and privacy receipt database models',
    'src/services/privacy_journal_transaction.py': 'privacy event transaction handling',
    'src/services/privacy_journal_outbox.py': 'privacy event outbox',
    'src/services/privacy_journal.py': 'privacy journal records',
    'src/services/privacy_journal_runtime.py': 'privacy journal and witness wiring',
    'src/services/privacy_journal_verify.py': 'privacy journal verification',
    'src/services/privacy_journal_mirror.py': 'independent journal mirror primitives',
    'src/services/privacy_purge_health.py': 'unresolved deletion queue health signal',
    'src/core/config.py': 'runtime and witness configuration',
    'src/services/storage.py': 'object deletion handling',
    'src/services/purge_queue.py': 'durable deletion queue',
    'src/services/account_scope.py': 'account media-scope key derivation',
    'src/services/account_recovery.py': 'account recovery and SQLite rollback handling',
    'src/services/tts.py': 'narration input and provider behavior',
}


def audit(report):
    ensure_local_daemon()
    if report.get('status') != 'LOCAL_CANDIDATES_BUILT':
        raise RuntimeError('Local candidate build report is required')
    before = checkout_hashes()
    trees = {role: source_hashes(report['images'][role]['candidate']) for role in ('api', 'worker')}
    after = checkout_hashes()
    if before != after:
        raise RuntimeError('Checkout changed during comparison; retry after concurrent edits')
    if trees['api'] != trees['worker']:
        raise RuntimeError('Candidate API and worker source trees differ')
    candidate = trees['api']
    changed = sorted(path for path in set(before) | set(candidate) if before.get(path) != candidate.get(path))
    critical = {path: {'feature': feature, 'present_in_checkout': path in before,
                       'present_in_candidate': path in candidate,
                       'matches_current_checkout': path in before and path in candidate and path not in changed}
                for path, feature in SENSITIVE_PATHS.items()}
    return {'status': 'SOURCE_DRIFT_REPORTED', 'differing_paths': changed,
            'sensitive_paths': critical, 'same_source_as_checkout': not changed,
            'production_deployment_authorized': False, 'privacy_restore_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.report.read_text())), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
