"""Regression checks for a source-pinned provider config overlay."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from provider_config_overlay import OverlayError, build_overlay


SOURCE = b'''from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    llm_api_key: str = ""\n    image_api_key: str = ""\nsettings = Settings()\n'''


class ProviderConfigOverlayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.key = self.root / 'provider.key'
        self.key.write_bytes(b'synthetic-fixture-provider-key')
        self.key.chmod(0o600)
        self.overlay = self.root / 'config.py'
        self.overlay.write_bytes(build_overlay(SOURCE, hashlib.sha256(SOURCE).hexdigest()))

    def run_overlay(self, **overrides):
        env = dict(os.environ, LLM_API_KEY='', IMAGE_API_KEY='',
                   LLM_API_KEY_FILE=str(self.key), IMAGE_API_KEY_FILE=str(self.key))
        env.update(overrides)
        code = '''import runpy,sys\ns=runpy.run_path(sys.argv[1])['settings']\nassert s.llm_api_key == s.image_api_key == 'synthetic-fixture-provider-key'\nassert 'synthetic-fixture-provider-key' not in repr(s)\nassert 'synthetic-fixture-provider-key' not in s.model_dump_json()\n'''
        return subprocess.run([sys.executable, '-c', code, str(self.overlay)], env=env,
                              capture_output=True, text=True, timeout=20)

    def test_same_private_file_loads_both_and_is_not_serialized(self):
        self.assertEqual(self.run_overlay().returncode, 0)

    def test_world_readable_or_symlink_file_is_rejected(self):
        self.key.chmod(0o640)
        self.assertNotEqual(self.run_overlay().returncode, 0)
        self.key.chmod(0o600)
        link = self.root / 'link.key'
        link.symlink_to(self.key)
        self.assertNotEqual(self.run_overlay(LLM_API_KEY_FILE=str(link), IMAGE_API_KEY_FILE=str(link)).returncode, 0)

    def test_raw_key_collision_or_mismatched_paths_are_rejected(self):
        self.assertNotEqual(self.run_overlay(LLM_API_KEY='synthetic-old-key').returncode, 0)
        self.assertNotEqual(self.run_overlay(IMAGE_API_KEY_FILE='').returncode, 0)
        self.assertNotEqual(self.run_overlay(IMAGE_API_KEY_FILE=str(self.root / 'other.key')).returncode, 0)

    def test_source_digest_and_shape_are_enforced(self):
        with self.assertRaises(OverlayError):
            build_overlay(SOURCE, '0' * 64)
        invalid = SOURCE + b'print("unexpected")\n'
        with self.assertRaises(OverlayError):
            build_overlay(invalid, hashlib.sha256(invalid).hexdigest())


if __name__ == '__main__':
    unittest.main()
