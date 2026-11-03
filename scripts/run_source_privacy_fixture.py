"""Commit synthetic source privacy mutations and an outbox to a local fixture."""

import asyncio
import os

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    from sqlalchemy import select, update
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.exceptions import APIError
    from src.core.utils import utcnow
    from src.models.db import AccountIdentity, PrivacyJournalOutbox, UserConsent
    from src.services import account_recovery
    from src.routers.consent import ConsentGrantRequest, grant_consent, revoke_consent
    from src.routers.profiles import delete_profile
    from src.routers.users import delete_my_data
    from src.services.privacy_journal_outbox import prepare_privacy_event, publish_privacy_event
    from fixture_journal_store import load_fixture_journal

    scenario = os.environ.get('ASB_REPLAY_SCENARIO')
    if scenario == 'failed_enrollment':
        # Exercise the real PostgreSQL first-enrollment transaction with an
        # unavailable journal, without storing a non-synthetic credential.
        owner = '00000000-0000-4000-8000-000000000004'
        journal = load_fixture_journal()

        def fail_begin(*_args, **_kwargs):
            raise RuntimeError('synthetic journal outage')

        journal.begin = fail_begin
        try:
            async with AsyncSessionLocal() as db:
                db.info['privacy_journal'] = journal
                try:
                    await account_recovery.issue_recovery_code(db, owner, owner)
                except APIError as exc:
                    if exc.status_code != 503:
                        raise RuntimeError('Synthetic enrollment did not fail closed') from None
                else:
                    raise RuntimeError('Synthetic enrollment unexpectedly succeeded')
                if await db.get(AccountIdentity, owner) is not None or await db.scalar(
                    select(PrivacyJournalOutbox.event_id).where(PrivacyJournalOutbox.user_key == owner).limit(1)
                ) is not None:
                    raise RuntimeError('Synthetic failed enrollment left database state')
            print('Synthetic failed enrollment rolled back')
        finally:
            await async_engine.dispose()
        return
    if scenario == 'account':
        owner = '00000000-0000-4000-8000-000000000001'
        actions = ('account_delete',)
    elif scenario in {'historical', 'consent'}:
        owner = '00000000-0000-4000-8000-000000000003'
        actions = (('consent_revoke', 'consent_grant') if scenario == 'historical'
                   else ('profile_delete', 'consent_revoke', 'consent_grant', 'consent_revoke', 'credential_revoke'))
    else:
        raise RuntimeError('Invalid synthetic source scenario')
    journal = load_fixture_journal()
    try:
        for action in actions:
            async with AsyncSessionLocal() as db:
                if action in {'account_delete', 'consent_grant', 'profile_delete', 'credential_revoke'} or (
                    action == 'consent_revoke' and scenario == 'consent'
                ):
                    db.info['privacy_journal'] = journal
                    if action == 'account_delete':
                        await delete_my_data(db=db, user_key=owner, x_user_key='asb_device_' + 'A' * 43)
                    elif action == 'consent_revoke':
                        await revoke_consent(db=db, user_key=owner)
                    elif action == 'consent_grant':
                        await grant_consent(ConsentGrantRequest(privacy=True, photos=True,
                            data_processing=True, consent_version='v2'), db=db, user_key=owner)
                    elif action == 'profile_delete':
                        await delete_profile('profile-fixture', db=db, user_key=owner)
                    else:
                        # Fixed synthetic secrets never leave this disposable test.
                        account_recovery.secrets.token_urlsafe = lambda _: 'G' * 43
                        code, _ = await account_recovery.recover_account(db, 'ASB-R1-' + 'E' * 43,
                                                                         'asb_device_' + 'F' * 43)
                        if code != 'ASB-R1-' + 'G' * 43:
                            raise RuntimeError('Synthetic credential rotation failed')
                    continue
                event_id = await prepare_privacy_event(db, journal, user_key=owner, action=action)
                if action == 'consent_revoke':
                    await db.execute(update(UserConsent).where(
                        UserConsent.user_key == owner, UserConsent.revoked_at.is_(None)).values(
                        granted=False, photos=False, revoked_at=utcnow()))
                await db.commit()
            await publish_privacy_event(AsyncSessionLocal, journal, event_id)
        # The historical grant uses the same journaled API path as a real
        # grant. An unrecorded grant cannot prove the backup's state is safe.
        print('Synthetic source privacy events committed and journaled')
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
