"""Reserve fresh fictional accounts for store review without granting access."""

import argparse
import asyncio
import json
import uuid

from sqlalchemy import select

from src.core.config import settings
from src.core.consent import latest_active_consent
from src.core.database import Base, get_db
from src.core.generation_access import generation_access_allowed
from src.models.db import AccountIdentity, PrivacyJournalOutbox
from src.routers.consent import ConsentGrantRequest, grant_consent
from src.services.account_recovery import credential_hash
from src.services.guardian_email import issue_guardian_email
from src.services.privacy_journal import CredentialState
from src.services.privacy_journal_transaction import (
    guardian_consent_published,
    journal_attached,
    lock_account_before_credential_change,
    prepare_transaction_event,
    publish_committed_event,
)


async def verify_published(db, slots: list[str]) -> None:
    published = (await db.scalars(select(PrivacyJournalOutbox.user_key).where(
        PrivacyJournalOutbox.user_key.in_(slots),
        PrivacyJournalOutbox.action == "credential_revoke",
        PrivacyJournalOutbox.published_at.is_not(None),
    ))).all()
    if set(published) != set(slots):
        raise RuntimeError("Review reservations are not yet published to the privacy journal")


async def reserve_slots(slots: list[str]) -> None:
    if (
        not 1 <= len(slots) <= 32
        or len(slots) != len(set(slots))
        or any(uuid.UUID(slot).version != 4 or str(uuid.UUID(slot)) != slot for slot in slots)
    ):
        raise ValueError("Use 1 to 32 distinct, newly generated UUID4 slots")
    async for db in get_db():
        if db.get_bind().dialect.name != "postgresql" or not journal_attached(db):
            raise RuntimeError("Provisioning requires PostgreSQL and an attached privacy journal")
        slots = sorted(slots)
        for slot in slots:
            await lock_account_before_credential_change(db, slot)
        reservations = {slot: credential_hash(slot, kind="store-review-reservation") for slot in slots}
        existing = (await db.scalars(
            select(AccountIdentity).where(AccountIdentity.user_key.in_(slots))
        )).all()
        if existing:
            if len(existing) != len(slots) or any(
                row.deleted or row.device_key_hash != reservations[row.user_key]
                or row.recovery_code_hash is not None or row.previous_recovery_code_hash is not None
                for row in existing
            ):
                raise RuntimeError("A review slot already has account state")
            await verify_published(db, slots)
            print(json.dumps({"review_slots_reserved": len(slots)}))
            return
        for table in Base.metadata.tables.values():
            if "user_key" in table.c and await db.scalar(
                select(table.c.user_key).where(table.c.user_key.in_(slots)).limit(1)
            ):
                raise RuntimeError("A review slot already has account state")
        events = []
        for slot in slots:
            reserved = reservations[slot]
            db.add(AccountIdentity(user_key=slot, device_key_hash=reserved))
            events.append(await prepare_transaction_event(
                db, user_key=slot, action="credential_revoke",
                credential_state=CredentialState(reserved, None, None, None),
            ))
        await db.commit()
        for event in events:
            await publish_committed_event(db, event)
        await verify_published(db, slots)
        print(json.dumps({"review_slots_reserved": len(events)}))


async def prepare_slot_consent(slot: str, *, request_email: str | None = None) -> None:
    """Preconfigure a fictional review slot through the real email consent flow."""
    if (
        not settings.guardian_email_consent_enabled
        or slot not in settings.store_review_account_slots.split(",")
        or not generation_access_allowed(slot)
    ):
        raise RuntimeError("Consent provisioning requires an enabled, invited review slot")
    async for db in get_db():
        if db.get_bind().dialect.name != "postgresql" or not journal_attached(db):
            raise RuntimeError("Consent provisioning requires PostgreSQL and the privacy journal")
        await lock_account_before_credential_change(db, slot)
        identity = await db.scalar(select(AccountIdentity).where(AccountIdentity.user_key == slot))
        if (
            not identity or identity.deleted
            or identity.device_key_hash != credential_hash(slot, kind="store-review-reservation")
            or identity.recovery_code_hash is not None
            or identity.previous_recovery_code_hash is not None
            or identity.recovery_code_created_at is not None
        ):
            raise RuntimeError("Consent provisioning requires an unclaimed review reservation")
        consent = await latest_active_consent(db, slot)
        if consent is None:
            if request_email is not None:
                await db.commit()
                await issue_guardian_email(slot, request_email.strip())
                print(json.dumps({"review_consent_email_requested": True}))
                return
            await grant_consent(ConsentGrantRequest(privacy=True, data_processing=True), db, slot)
            consent = await latest_active_consent(db, slot)
        if consent is None or not await guardian_consent_published(db, consent):
            raise RuntimeError("Review consent is not yet published to the privacy journal")
        print(json.dumps({"review_slot_consent_ready": True}))


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["reserve", "request-consent", "finalize-consent"],
                        nargs="?", default="reserve")
    operation = parser.parse_args().operation
    payload = json.load(sys.stdin)
    if operation == "reserve":
        asyncio.run(reserve_slots(payload))
    else:
        email = payload["email"] if operation == "request-consent" else None
        if operation == "request-consent" and not isinstance(email, str):
            parser.error("request-consent needs an email address in the input JSON")
        asyncio.run(prepare_slot_consent(
            payload["slot"], request_email=email,
        ))
