"""Fail-closed encrypted journal mirroring primitives.

The caller must establish that the two stores use independent administrative
and failure domains. A successful match is not proof against simultaneous loss
or a shared rollback and never authorizes a production restore.
"""
import hmac

from src.services.privacy_journal import JournalError


class MirroredJournalStore:
    """Require byte-identical, create-only records in both configured stores."""

    def __init__(self, primary, witness):
        if primary is witness:
            raise JournalError('A separate witness store is required')
        self._primary = primary
        self._witness = witness

    def close(self):
        """Close independently owned clients even if the first close fails."""
        failure = False
        for store in (self._primary, self._witness):
            try:
                close = getattr(store, 'close', None)
                if close is not None:
                    close()
            except Exception:
                failure = True
        if failure:
            raise JournalError('Journal mirror clients could not be closed')

    @staticmethod
    def _create_one(store, name, data):
        try:
            store.create(name, data)
        except Exception:
            # A timeout can follow a completed create. Accept only the exact
            # immutable bytes; never replace a conflicting prior record.
            try:
                existing = store.read(name)
                if not isinstance(existing, bytes) or not hmac.compare_digest(existing, data):
                    raise ValueError('record conflict')
            except Exception:
                raise JournalError('Journal mirror write could not be verified') from None

    def create(self, name, data):
        if not isinstance(data, bytes) or not data:
            raise JournalError('Invalid journal mirror record')
        self._create_one(self._primary, name, data)
        self._create_one(self._witness, name, data)
        # A store implementation must return exactly what it accepted. This
        # check also catches a provider acknowledging a truncated write.
        if not hmac.compare_digest(self.read(name), data):
            raise JournalError('Journal mirror write could not be verified')

    def reconcile(self, name, validate):
        """Copy one authenticated existing ciphertext into a missing replica.

        The journal supplies a validator that authenticates the record and
        compares the *entire* expected intent/commit/abort payload. No existing
        bytes may be overwritten, including an independently encrypted but
        semantically identical record. A read failure is treated as unknown;
        create-only and final two-sided reads must still succeed.
        """
        if not callable(validate):
            raise JournalError('Journal mirror reconciliation is invalid')
        records = []
        for store in (self._primary, self._witness):
            try:
                records.append(store.read(name))
            except Exception:
                records.append(None)
        present = [record for record in records if record is not None]
        if (not present or any(not isinstance(record, bytes) or not record for record in present)
                or any(not hmac.compare_digest(present[0], record) for record in present[1:])):
            raise JournalError('Journal mirror reconciliation could not be verified')
        candidate = present[0]
        try:
            if validate(candidate) is not True:
                raise ValueError('payload mismatch')
            for store, value in zip((self._primary, self._witness), records):
                if value is None:
                    self._create_one(store, name, candidate)
            if not hmac.compare_digest(self.read(name), candidate):
                raise ValueError('replica mismatch')
        except Exception:
            raise JournalError('Journal mirror reconciliation could not be verified') from None

    def read(self, name):
        try:
            first = self._primary.read(name)
            second = self._witness.read(name)
            if not isinstance(first, bytes) or not isinstance(second, bytes) or not hmac.compare_digest(first, second):
                raise ValueError('mismatched replicas')
            return first
        except Exception:
            raise JournalError('Journal replicas do not agree') from None

    def list_names(self, prefix):
        try:
            first = self._primary.list_names(prefix)
            second = self._witness.list_names(prefix)
            if (not isinstance(first, list) or not isinstance(second, list)
                    or any(not isinstance(name, str) or not name.startswith(prefix) for name in first + second)
                    or len(first) != len(set(first)) or len(second) != len(set(second))
                    or set(first) != set(second)):
                raise ValueError('mismatched replica listings')
            return sorted(first)
        except Exception:
            raise JournalError('Journal replica listings do not agree') from None
