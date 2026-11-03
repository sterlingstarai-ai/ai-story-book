"""Resume the single stopped provider cutover candidate set from 2026-11-03.

Default is a limited read-only preparation check.  This script never creates
candidates.  --execute passes the exact owned set to the existing cutover state
machine, which performs full staged verification again under its backup lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re

import provider_candidate_stage as stage
from provider_cutover_drained import _run
from provider_cutover_production_adapter import KEY_PATH, OVERLAY_PATH, STATE, ProductionAdapter
from provider_cutover_production_entry import (
    BACKUP, OTHER_MARKERS, _expected_overlay, _read_env, verify_instance,
)
from provider_cutover_production_guards import verify_installed_guard_files, verify_loaded_units
from provider_cutover_production_adapter import _systemd_show
from provider_cutover_production_runtime import API_IMAGE, OLD_API, OLD_WORKER, WORKER_IMAGE

# These are the two stopped, no-restart candidates observed in the interrupted
# transaction. A different transaction or candidate set requires a new review.
NEW_API = 'de6e69d030891629add23efe6693994ca967ef5cdd2212fd5c2dd1f9180a53ac'
NEW_WORKER = '261c766495fac9f0c8ecf92f8cbf1dd118a753e56eb6b3c934c1ad9c592fa99e'


def run(*, transaction, execute=False):
    if not isinstance(transaction, str) or not re.fullmatch(r'[0-9a-f]{32}', transaction):
        raise ValueError('Invalid transaction identity')
    ids = {'old_api': OLD_API, 'old_worker': OLD_WORKER, 'new_api': NEW_API, 'new_worker': NEW_WORKER}
    owner = stage._candidate_owner_record(transaction_id=transaction, ids=ids)
    verify_instance()
    verify_installed_guard_files()
    verify_loaded_units(_systemd_show)
    stage._read_owned_record(STATE / 'candidate-owner.json', owner)
    environment = _read_env()
    overlay_sha = hashlib.sha256(_expected_overlay()).hexdigest()
    stage.capture_bound_file_evidence(overlay_path=OVERLAY_PATH, overlay_sha256=overlay_sha, key_path=KEY_PATH)
    if not execute:
        return {'status': 'OWNED_RESUME_READ_ONLY_CHECK_PASSED', 'production_changed': False,
                'cutover_ready': False}
    images = {'old_api': API_IMAGE, 'new_api': API_IMAGE, 'old_worker': WORKER_IMAGE, 'new_worker': WORKER_IMAGE}
    runtime = ProductionAdapter(ids=ids, transaction=transaction, environment=environment, overlay_sha256=overlay_sha)
    return _run(state_dir=STATE, backup_dir=BACKUP, ids=ids, images=images,
                other_markers=OTHER_MARKERS, runtime=runtime, production=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transaction', required=True, help='Exact existing candidate owner transaction ID')
    parser.add_argument('--execute', action='store_true', help='Resume the owned, staged cutover')
    args = parser.parse_args()
    try:
        result = run(transaction=args.transaction, execute=args.execute)
    except BaseException:
        print(json.dumps({'status': 'FAILED_OR_INDETERMINATE', 'recovery_markers_must_be_preserved': True}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
