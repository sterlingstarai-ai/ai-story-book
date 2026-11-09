"""Production preflight accepts configured providers and rejects mismatched releases."""
import os
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from src.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]
WITNESS = {'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT': 'https://witness.test',
           'PRIVACY_JOURNAL_WITNESS_S3_BUCKET': 'witness-bucket',
           'PRIVACY_JOURNAL_WITNESS_S3_REGION': 'us-east-1',
           'PRIVACY_JOURNAL_WITNESS_S3_ACCESS_KEY': 'witness-access',
           'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY': 'witness-secret'}


@pytest.mark.parametrize("overrides,passes", [
    ({}, True),
    ({"OPENAI_IMAGE_QUALITY": "low"}, True),
    ({"OPENAI_IMAGE_QUALITY": "medium"}, True),
    ({"OPENAI_IMAGE_QUALITY": "high"}, True),
    ({"OPENAI_IMAGE_QUALITY": "auto"}, True),
    ({"OPENAI_IMAGE_QUALITY": "hd"}, False),
    ({"IMAGE_MAX_CONCURRENT": "4"}, True),
    ({"IMAGE_MAX_CONCURRENT": "0"}, False),
    ({"LLM_PROVIDER": "gemini", "LLM_MODEL": "gemini-test"}, False),
    ({"ILLUSTRATION_QUALITY_ENABLED": "false"}, False),
    ({"ILLUSTRATION_QUALITY_ENABLED": "invalid"}, False),
    ({"LLM_MODEL": "gpt-6-astra"}, True),
    ({"IMAGE_PROVIDER": "mock"}, False),
    ({"LLM_MODEL": "gpt-4o-mini"}, False),
    ({"IMAGE_MODEL": "dall-e-3"}, False),
    ({"IMAGE_API_KEY": ""}, False),
    ({"IMAGE_API_KEY": "", "IMAGE_API_KEY_FILE": "/run/asb-provider-keys/key"}, True),
    ({"IMAGE_API_KEY_FILE": "/run/asb-provider-keys/key"}, False),
    ({"IMAGE_API_KEY": "", "IMAGE_API_KEY_FILE": "relative"}, False),
    ({"POD_ORDERING_ENABLED": "true", "POD_MODE": "local"}, False),
    ({'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT': 'https://witness.test'}, False),
    (WITNESS, True),
    ({**WITNESS, 'PRIVACY_JOURNAL_WITNESS_BUCKET': 'other-witness'}, False),
    ({**WITNESS, 'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT': 'http://witness.test'}, False),
    ({**WITNESS, 'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY': 'test-key'}, False),
])
def test_production_env_validation(tmp_path, overrides, passes):
    values = {
        "DB_USER": "storybook", "DB_PASSWORD": "test-pass", "DB_NAME": "storybook",
        "LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-5.6-sol", "LLM_API_KEY": "test-key",
        "ILLUSTRATION_QUALITY_ENABLED": "true",
        "IMAGE_PROVIDER": "gemini", "IMAGE_MODEL": "gemini-3-pro-image", "IMAGE_API_KEY": "test-key",
        "S3_ENDPOINT": "https://storage.test", "S3_ACCESS_KEY": "test-key",
        "S3_SECRET_KEY": "test-key", "S3_BUCKET": "storybook", "CORS_ORIGINS": "https://app.test",
        "IAP_VERIFICATION_MODE": "strict", "IAP_WEBHOOK_SECRET": "test-key",
        "POD_ORDERING_ENABLED": "false",
        "PROD_API_URL": "https://api.storybook.test",
    }
    values.update(overrides)
    env_file = tmp_path / 'release.env'
    env_file.write_text('\n'.join(f'{key}={value}' for key, value in values.items()))
    result = subprocess.run(
        ['bash', str(ROOT / 'scripts/check-env.sh'), '--mode', 'production', '--env-file', str(env_file)],
        capture_output=True, text=True, env={**os.environ, **values},
    )
    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    assert 'test-key' not in result.stdout


def test_image_concurrency_cannot_start_a_worker_without_slots():
    with pytest.raises(ValidationError, match="image_max_concurrent"):
        Settings(_env_file=None, image_max_concurrent=0)
