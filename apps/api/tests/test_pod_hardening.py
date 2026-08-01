"""POD 하드닝 회귀 — 감사 확정 #15/#16/#18.

#18: 기존 멱등 테스트는 순차 재요청만 검증해 라우터 앱 레벨 pre-check만으로 통과했다.
     DB 부분 유니크 제약을 제거해도 green이던 false-green — 제약 자체와 IntegrityError
     흡수 분기(동시 더블탭 경로)를 직접 검증한다.
#16: strict 제출 확정 실패로 남은 pending_submit 행이 재요청에서 '접수 성공'으로 위장되던
     경로 — 재제출을 시도해야 한다.
#15: 상태 조회 중 Printful 타임아웃(PodSubmitUnknown)이 미처리 500이 되던 경로.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.db import PodOrder


def _order(user_key: str, idem, status: str = "pending_submit", book_id: str = "book-x") -> PodOrder:
    return PodOrder(
        id=f"pod_{uuid.uuid4().hex[:10]}",
        user_key=user_key,
        book_id=book_id,
        idempotency_key=idem,
        provider="printful",
        status=status,
        quantity=1,
        unit_price=1000,
        shipping_fee=0,
        total_price=1000,
        currency="KRW",
        shipping_address={"name": "n", "line1": "l", "postal_code": "1", "country": "KR"},
    )


# ───────────────── #18: DB 부분 유니크 제약이 실제로 존재하는가 ─────────────────


@pytest.mark.asyncio
async def test_pod_orders_partial_unique_blocks_duplicate_idempotency_key(db_session):
    """같은 (user_key, idempotency_key) PodOrder 2행 직접 insert → 2번째는 IntegrityError.

    라우터 pre-check를 우회한 동시 더블탭에서 이중 실물 주문(이중 과금 + Printful 이중 실비)을
    막는 최종 방어선. 제약이 사라져도 기존 순차 테스트는 green이라 이 테스트가 정본.
    """
    from tests.test_phase_new_endpoints import _seed_pod_book

    uk = f"pod-uniq-{uuid.uuid4().hex[:6]}"
    book = await _seed_pod_book(db_session, {"X-User-Key": uk}, f"bk-{uk}")
    db_session.add(_order(uk, "dup-key", book_id=book.id))
    await db_session.commit()

    db_session.add(_order(uk, "dup-key", book_id=book.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_pod_orders_unique_allows_null_idempotency_key(db_session):
    """멱등키 없는 주문은 부분 유니크에서 제외(NULL 다건 허용)."""
    from tests.test_phase_new_endpoints import _seed_pod_book

    uk = f"pod-null-{uuid.uuid4().hex[:6]}"
    book = await _seed_pod_book(db_session, {"X-User-Key": uk}, f"bk-{uk}")
    db_session.add(_order(uk, None, book_id=book.id))
    db_session.add(_order(uk, None, book_id=book.id))
    await db_session.commit()

    rows = (
        await db_session.execute(select(PodOrder).where(PodOrder.user_key == uk))
    ).scalars().all()
    assert len(rows) == 2


# ───────────────── #16: 미제출 주문은 재요청에서 재제출된다 ─────────────────


@pytest.mark.asyncio
async def test_pending_submit_order_is_resubmitted_not_reported_success(
    client, headers, db_session, monkeypatch
):
    """provider 장애로 남은 pending_submit 행이 재요청에서 외부 재제출을 시도해야 한다."""
    from src.routers import pod as pod_router
    from tests.test_phase_new_endpoints import _pod_result, _seed_pod_book

    book = await _seed_pod_book(db_session, headers, "book-resubmit")

    # 1차 제출이 확정 실패해 pending_submit로 남은 상황을 그대로 재현.
    stale = _order(headers["X-User-Key"], "resubmit-key", book_id=book.id)
    db_session.add(stale)
    await db_session.commit()

    calls = {"n": 0}

    async def _stub(**kwargs):
        calls["n"] += 1
        return _pod_result()

    monkeypatch.setattr(pod_router.pod_provider_service, "create_order", _stub)

    body = {
        "book_id": book.id,
        "quantity": 1,
        "shipping_address": {
            "name": "홍길동", "line1": "서울 1", "postal_code": "12345", "country": "KR"
        },
    }
    r = await client.post(
        "/v1/pod/orders",
        json=body,
        headers={**headers, "X-Idempotency-Key": "resubmit-key"},
    )
    assert r.status_code == 200, r.text
    assert calls["n"] == 1, "미제출(pending_submit) 주문은 재요청에서 외부 재제출돼야 함"
    assert r.json()["order_id"] == stale.id, "새 행을 만들지 말고 기존 행을 재사용해야 함"


@pytest.mark.asyncio
async def test_submitted_order_is_not_resubmitted(client, headers, db_session, monkeypatch):
    """이미 제출된 주문은 재요청에서 재제출하지 않는다(과잉 재제출 방지)."""
    from src.routers import pod as pod_router
    from tests.test_phase_new_endpoints import _pod_result, _seed_pod_book

    book = await _seed_pod_book(db_session, headers, "book-nosubmit")
    submitted = _order(headers["X-User-Key"], "done-key", status="submitted", book_id=book.id)
    submitted.provider_order_id = "prov-1"
    db_session.add(submitted)
    await db_session.commit()

    calls = {"n": 0}

    async def _stub(**kwargs):
        calls["n"] += 1
        return _pod_result()

    monkeypatch.setattr(pod_router.pod_provider_service, "create_order", _stub)

    body = {
        "book_id": book.id,
        "quantity": 1,
        "shipping_address": {
            "name": "홍길동", "line1": "서울 1", "postal_code": "12345", "country": "KR"
        },
    }
    r = await client.post(
        "/v1/pod/orders",
        json=body,
        headers={**headers, "X-Idempotency-Key": "done-key"},
    )
    assert r.status_code == 200, r.text
    assert calls["n"] == 0


# ───────────────── #15: 상태 조회 타임아웃이 500이 아니어야 한다 ─────────────────


@pytest.mark.asyncio
async def test_get_pod_order_survives_provider_timeout(
    client, headers, db_session, monkeypatch
):
    """Printful 타임아웃(PodSubmitUnknown)에도 로컬 스냅샷 200을 반환한다(L6 DoD)."""
    from src.routers import pod as pod_router
    from src.services.pod_provider import PodSubmitUnknown

    from tests.test_phase_new_endpoints import _seed_pod_book

    book = await _seed_pod_book(db_session, headers, "book-timeout")
    order = _order(
        headers["X-User-Key"], f"timeout-{uuid.uuid4().hex[:6]}",
        status="submitted", book_id=book.id,
    )
    order.provider_order_id = "prov-timeout"
    db_session.add(order)
    await db_session.commit()

    async def _timeout(**kwargs):
        raise PodSubmitUnknown("printful timeout")

    monkeypatch.setattr(pod_router.pod_provider_service, "sync_order_status", _timeout)

    r = await client.get(f"/v1/pod/orders/{order.id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"
