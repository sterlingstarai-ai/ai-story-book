import os
import subprocess
import sys

from src.core.config import Settings, settings


def test_settings_repr_never_contains_secrets():
    obj = Settings(_env_file=None, llm_api_key='secret-canary', database_url='postgresql://u:secret-canary@host/db')
    assert 'secret-canary' not in repr(obj)
    assert 'secret-canary' not in str(obj)


def test_pytest_settings_do_not_load_local_env_file():
    assert settings.llm_api_key is None or settings.llm_api_key == os.getenv('LLM_API_KEY')
    code = "from src.core.config import Settings; print(Settings().llm_api_key is None)"
    env = {**os.environ, 'TESTING': 'true', 'ASB_TEST_ISOLATED_SETTINGS': '1'}
    env.pop('LLM_API_KEY', None)
    result = subprocess.run([sys.executable, '-c', code], env=env, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == 'True'
