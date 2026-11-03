"""Replay one synthetic deletion in a loopback-only disposable restore fixture.

This is not a production restore tool and always leaves restore authorization off.
"""

import asyncio
import os
from urllib.parse import urlsplit


def require_local_fixture():
    database = urlsplit(os.environ.get('DATABASE_URL', ''))
    storage = urlsplit(os.environ.get('S3_ENDPOINT', ''))
    if not (os.environ.get('TESTING') == 'true'
            and database.scheme == 'postgresql+asyncpg'
            and database.hostname == '127.0.0.1'
            and database.username == 'runtime_test'
            and database.password == 'disposable-runtime-password'
            and database.path == '/runtime_test'
            and storage.scheme == 'http' and storage.hostname == '127.0.0.1'
            and os.environ.get('S3_BUCKET') == 'restore-rehearsal'):
        raise RuntimeError('Only the explicitly configured disposable local fixture is allowed')


async def main():
    require_local_fixture()
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.exceptions import APIError
    from src.models.db import AccountIdentity, ChildProfile
    from src.services.account_recovery import credential_hash, recover_account, resolve_user_key
    from fixture_journal_store import load_fixture_journal
    from replay_privacy_journal import replay_quarantined

    journal = load_fixture_journal()
    scenario = os.environ.get('ASB_REPLAY_SCENARIO', 'account')
    if scenario == 'account':
        subject = '00000000-0000-4000-8000-000000000001'
        actions = ('account_delete',)
        device = 'asb_device_' + 'A' * 43
        recovery = 'ASB-R1-' + 'C' * 43
    elif scenario == 'consent':
        subject = '00000000-0000-4000-8000-000000000003'
        actions = ('profile_delete', 'consent_revoke', 'consent_grant', 'consent_revoke', 'credential_revoke')
        device = 'asb_device_' + 'B' * 43
        recovery = 'ASB-R1-' + 'E' * 43
    else:
        raise RuntimeError('Unsupported synthetic replay scenario')
    try:
        async with AsyncSessionLocal() as session:
            run_number = os.environ.get('ASB_REPLAY_RUN')
            if run_number not in {'1', '2'}:
                raise RuntimeError('Synthetic replay run number is invalid')
            try:
                before_allowed = (await resolve_user_key(session, device)) == subject
            except APIError:
                before_allowed = False
            if before_allowed != (run_number == '1'):
                raise RuntimeError('Synthetic pre-replay authentication state was unexpected')
            result = await replay_quarantined(session, journal.scan())
            # Both scenarios include checkpointed withdrawal and regrant;
            # the consent scenario also sees the other account's deletion.
            other_events = 2 if scenario == 'account' else 3
            if result != {'status': 'REPLAYED_STILL_QUARANTINED', 'subject_count': 2,
                          'event_count': len(actions) + other_events, 'applied_count': len(actions) if run_number == '1' else 0,
                          'voice_state_recovery_supported': False,
                          'restore_authorized': False}:
                raise RuntimeError('Synthetic replay result was unexpected')
            try:
                await resolve_user_key(session, device)
            except APIError:
                pass
            else:
                raise RuntimeError('Synthetic old device credential still works')
            try:
                await recover_account(session, recovery, 'asb_device_' + 'D' * 43)
            except APIError:
                pass
            else:
                raise RuntimeError('Synthetic old recovery credential still works')
            if scenario == 'consent':
                if await session.get(ChildProfile, 'profile-fixture') is not None:
                    raise RuntimeError('Synthetic deleted profile was restored')
                if await resolve_user_key(session, 'asb_device_' + 'F' * 43) != subject:
                    raise RuntimeError('Synthetic latest device credential was not preserved')
                identity = await session.get(AccountIdentity, subject)
                if identity.recovery_code_hash != credential_hash('ASB-R1-' + 'G' * 43, kind='recovery'):
                    raise RuntimeError('Synthetic latest recovery verifier was not preserved')
        print('Synthetic replay applied; restored target remains quarantined')
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
