"""Offline regression checks for explicitly channel-bound PostgreSQL URLs."""

import ssl
import unittest
from unittest.mock import patch

from sqlalchemy.engine import make_url

from src.core.database_options import database_options


class PsycopgDatabaseOptionsTests(unittest.TestCase):
    def test_explicit_psycopg_preserves_required_security_for_both_engines(self):
        raw = ("postgresql+psycopg://name:p%40ss%25word@example.invalid:5432/story"
               "?sslmode=verify-full&channel_binding=require")
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                url, options = database_options(raw, asynchronous=asynchronous)
                parsed = make_url(url)
                self.assertEqual(parsed.drivername, "postgresql+psycopg")
                self.assertEqual(parsed.password, "p@ss%word")
                self.assertEqual(parsed.query, {"sslmode": "verify-full",
                                                "channel_binding": "require",
                                                "sslrootcert": "system"})
                self.assertEqual(options, {})

    def test_explicit_ca_is_checked_and_retained(self):
        raw = ("postgresql+psycopg://name:secret@example.invalid/story"
               "?sslmode=verify-full&channel_binding=require&sslrootcert=/qa/ca.crt")
        with patch.object(ssl, "create_default_context") as create_context:
            url, _ = database_options(raw, asynchronous=True)
        create_context.assert_called_once_with(cafile="/qa/ca.crt")
        self.assertEqual(make_url(url).query["sslrootcert"], "/qa/ca.crt")

    def test_explicit_psycopg_rejects_weaker_security_and_invalid_ca(self):
        base = "postgresql+psycopg://name:secret-marker@example.invalid/story"
        for suffix in ("", "?sslmode=require&channel_binding=require",
                       "?sslmode=verify-full", "?sslmode=verify-full&channel_binding=prefer",
                       "?sslmode=verify-full&channel_binding=require&channel_binding=disable",
                       "?sslmode=verify-full&sslmode=disable&channel_binding=require",
                       "?sslmode=verify-full&channel_binding=require&sslrootcert=/not/a/ca.pem"):
            for asynchronous in (False, True):
                with self.subTest(suffix=suffix, asynchronous=asynchronous):
                    with self.assertRaises(ValueError) as error:
                        database_options(base + suffix, asynchronous=asynchronous)
                    self.assertNotIn("secret-marker", str(error.exception))

    def test_asyncpg_rejects_unsupported_channel_binding_without_secret(self):
        raw = "postgresql://name:secret-marker@example.invalid/story?channel_binding=require"
        with self.assertRaises(ValueError) as error:
            database_options(raw, asynchronous=True)
        self.assertIn("asyncpg does not support channel_binding", str(error.exception))
        self.assertNotIn("secret-marker", str(error.exception))
        # Existing sync/Alembic libpq path continues to preserve the option.
        url, _ = database_options(raw, asynchronous=False)
        self.assertEqual(make_url(url).query["channel_binding"], "require")

    def test_existing_postgresql_driver_and_sqlite_are_unchanged(self):
        raw = "postgresql://name:secret@example.invalid/story?sslmode=verify-full"
        async_url, options = database_options(raw, asynchronous=True)
        sync_url, _ = database_options(raw, asynchronous=False)
        self.assertEqual(make_url(async_url).drivername, "postgresql+asyncpg")
        self.assertTrue(options["ssl"].check_hostname)
        self.assertEqual(options["ssl"].verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(make_url(sync_url).drivername, "postgresql")
        sqlite_url, options = database_options("sqlite:///test.db", asynchronous=True)
        self.assertEqual(make_url(sqlite_url).drivername, "sqlite+aiosqlite")
        self.assertEqual(options, {})


if __name__ == "__main__":
    unittest.main()
