"""Opt-in Celery Redis namespace configuration without a shared test database."""

import json
import os
import subprocess
import sys
import unittest


class CeleryRedisNamespaceTests(unittest.TestCase):
    def inspect_worker(self, **overrides):
        # The child does not start a worker or contact Redis or any AI provider.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "TESTING": "true",
            "LLM_PROVIDER": "mock",
            "IMAGE_PROVIDER": "mock",
            "CELERY_REDIS_NAMESPACE": "",
            "CELERY_BROKER_URL": "redis://localhost:6379/1",
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
            **overrides,
        }
        code = (
            "import json; from src.worker import celery_app; "
            "print(json.dumps([celery_app.conf.broker_transport_options, "
            "celery_app.conf.result_backend_transport_options]))"
        )
        return subprocess.run(
            [sys.executable, "-c", code], env=env, text=True, capture_output=True,
            timeout=20, check=False,
        )

    def test_default_preserves_unprefixed_separate_databases(self):
        result = self.inspect_worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), [{}, {}])

    def test_enabled_namespaces_distinguish_broker_and_result(self):
        result = self.inspect_worker(
            CELERY_REDIS_NAMESPACE="story_test-1",
            CELERY_BROKER_URL="redis://localhost:6379/0",
            CELERY_RESULT_BACKEND="redis://localhost:6379/0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), [
            {"global_keyprefix": "story_test-1:broker:"},
            {"global_keyprefix": "story_test-1:result:"},
        ])

    def test_invalid_namespaces_and_nonredis_urls_fail_closed(self):
        for options in (
            {"CELERY_REDIS_NAMESPACE": "unsafe:prefix"},
            {"CELERY_REDIS_NAMESPACE": "a" * 65},
            {"CELERY_REDIS_NAMESPACE": "safe", "CELERY_BROKER_URL": "amqp://localhost/"},
            {"CELERY_REDIS_NAMESPACE": "safe", "CELERY_RESULT_BACKEND": "rpc://"},
        ):
            with self.subTest(options=options):
                result = self.inspect_worker(**options)
                self.assertNotEqual(result.returncode, 0)

    def test_invalid_redis_url_does_not_expose_credentials(self):
        result = self.inspect_worker(
            CELERY_REDIS_NAMESPACE="safe",
            CELERY_BROKER_URL="rediss://user:synthetic-secret@example.com:bad/0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("synthetic-secret", result.stdout + result.stderr)

    def test_secure_redis_urls_are_supported(self):
        result = self.inspect_worker(
            CELERY_REDIS_NAMESPACE="safe",
            CELERY_BROKER_URL="rediss://example.com:6379/0?ssl_cert_reqs=required",
            CELERY_RESULT_BACKEND="rediss://example.com:6379/0?ssl_cert_reqs=required",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip())[0],
                         {"global_keyprefix": "safe:broker:"})

    def test_api_tasks_bind_to_configured_application_before_worker_import(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "TESTING": "true", "LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "mock",
            "CELERY_REDIS_NAMESPACE": "api_probe",
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
        }
        code = (
            "from src.services.tasks import generate_book_task; "
            "from src.worker import celery_app; "
            "assert generate_book_task.app is celery_app; "
            "assert generate_book_task.app.conf.broker_transport_options"
            "['global_keyprefix'] == 'api_probe:broker:'"
        )
        result = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configured_task_still_supports_eager_execution(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "TESTING": "true", "LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "mock",
            "CELERY_REDIS_NAMESPACE": "eager_probe",
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
        }
        code = '''
from unittest.mock import AsyncMock, patch
from src.services.tasks import generate_book_task
from src.worker import celery_app
celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
with patch("src.services.tasks._run_book_task_async", new_callable=AsyncMock,
           return_value={"status": "success"}) as run:
    result = generate_book_task.delay("synthetic-job", {}, "synthetic-user")
    assert result.get() == {"status": "success"}
    run.assert_awaited_once_with("synthetic-job", {}, "synthetic-user")
'''
        result = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
