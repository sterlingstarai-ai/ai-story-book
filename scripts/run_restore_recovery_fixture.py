"""Exercise a synthetic recovered credential on the quarantined local fixture."""

import asyncio

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.exceptions import APIError
    from src.services.account_recovery import recover_account, resolve_user_key
    from replay_privacy_journal import _require_disposable_fixture

    subject = '00000000-0000-4000-8000-000000000003'
    recovery = 'ASB-R1-' + 'G' * 43
    old_device = 'asb_device_' + 'F' * 43
    new_device = 'asb_device_' + 'H' * 43
    try:
        async with AsyncSessionLocal() as session:
            await _require_disposable_fixture(session)
            next_recovery, _ = await recover_account(session, recovery, new_device)
            if not next_recovery or await resolve_user_key(session, new_device) != subject:
                raise RuntimeError('Synthetic latest recovery credential did not work')
            try:
                await resolve_user_key(session, old_device)
            except APIError:
                pass
            else:
                raise RuntimeError('Synthetic rotated device credential remained active')
            try:
                await recover_account(session, recovery, 'asb_device_' + 'I' * 43)
            except APIError:
                pass
            else:
                raise RuntimeError('Synthetic consumed recovery credential was reusable')
        print('Synthetic latest recovery credential works once; previous credentials are rejected')
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
