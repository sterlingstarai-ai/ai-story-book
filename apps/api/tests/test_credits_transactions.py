from unittest.mock import AsyncMock, patch

import pytest

from src.core.exceptions import InternalServerError
from src.routers.credits import SubscribeRequest, subscribe


class _FakeDbSession:
    def __init__(self):
        self.rollback_calls = 0

    async def rollback(self):
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_subscribe_rolls_back_on_service_failure():
    db = _FakeDbSession()
    request = SubscribeRequest(plan="basic")

    with patch(
        "src.routers.credits.credits_service.create_subscription",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(InternalServerError):
            await subscribe(request=request, db=db, user_key="user-12345678")

    assert db.rollback_calls == 1
