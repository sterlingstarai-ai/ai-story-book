import os
import unittest
from unittest import mock

from provider_environment import ProviderEnvironmentError, create_environment_memfd, sanitize_environment


class ProviderEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.source = (b'# fixture\nLLM_API_KEY=old-llm\nIMAGE_API_KEY=old-image\n'
                       b'DATABASE_URL=secret-database-value\n')

    def test_removes_only_old_provider_keys_and_adds_file_paths(self):
        result = sanitize_environment(self.source)
        self.assertNotIn(b'old-llm', result)
        self.assertNotIn(b'old-image', result)
        self.assertIn(b'DATABASE_URL=secret-database-value\n', result)
        self.assertIn(b'LLM_API_KEY_FILE=/run/asb-provider-keys/provider.key\n', result)
        self.assertIn(b'IMAGE_API_KEY_FILE=/run/asb-provider-keys/provider.key\n', result)

    def test_rejects_duplicates_ambiguous_fields_and_unsafe_formats(self):
        cases = [self.source + b'LLM_API_KEY=duplicate\n',
                 self.source + b'LLM_API_KEY_FILE=/other\n',
                 b'LLM_API_KEY=x\n',
                 self.source + b'export VALUE=x\n',
                 self.source + b'MISSING_EQUALS\n',
                 self.source + b'BAD\r\n',
                 self.source + b'BAD=\x00\n']
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ProviderEnvironmentError):
                sanitize_environment(item)
        with self.assertRaises(ProviderEnvironmentError):
            sanitize_environment(self.source, container_key_path='/tmp/provider.key')

    def test_missing_memfd_fails_closed(self):
        with mock.patch.object(os, 'memfd_create', create=True, new=None):
            with self.assertRaises(ProviderEnvironmentError):
                create_environment_memfd(self.source)


if __name__ == '__main__':
    unittest.main()
