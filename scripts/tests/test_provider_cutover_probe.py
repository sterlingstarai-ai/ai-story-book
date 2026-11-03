import asyncio
from contextlib import contextmanager
import io
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_probe as probe


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.prefix = None
        self.settings = SimpleNamespace(llm_provider='openai', llm_model='gpt-5.6-sol',
                                        image_provider='openai', image_model='gpt-image-2', s3_bucket='test-bucket')
        self.text = '{"ok": true}'
        async def llm(*_, **__):
            async with httpx.AsyncClient() as client:
                await client.send(httpx.Request('POST', 'https://api.openai.com/v1/responses',
                                                json={'model': 'gpt-5.6-sol', 'max_output_tokens': 4160}))
            return self.text
        async def image(*_, **__):
            async with httpx.AsyncClient() as client:
                await client.send(httpx.Request('POST', 'https://api.openai.com/v1/images/generations',
                                                json={'model': 'gpt-image-2', 'n': 1}))
            return 'https://example.invalid/image'
        self.call_llm = AsyncMock(side_effect=llm)
        self.image = AsyncMock(side_effect=image)
        self.cleanup = AsyncMock(return_value=[])
        self.status = AsyncMock(return_value={'status': 'healthy'})
        data = io.BytesIO()
        Image.new('RGB', (4, 4), 'yellow').save(data, format='PNG')
        self.read = AsyncMock(return_value=(data.getvalue(), 'image/png'))
        self.modules = {}
        for name in ('src', 'src.core', 'src.models', 'src.services', 'src.core.config',
                     'src.models.dto', 'src.services.image', 'src.services.llm',
                     'src.services.provider_runtime', 'src.services.storage'):
            module = ModuleType(name)
            module.__path__ = []
            self.modules[name] = module
        self.modules['src.core.config'].settings = self.settings
        self.modules['src.models.dto'].ImagePrompt = lambda **values: values
        self.modules['src.services.llm'].call_llm = self.call_llm
        self.modules['src.services.image'].generate_image = self.image
        self.modules['src.services.provider_runtime'].provider_runtime_status = self.status
        self.modules['src.services.storage']._delete_prefix_keys = self.cleanup
        self.storage_client = SimpleNamespace(list_objects_v2=lambda **_: {'IsTruncated': False})
        self.modules['src.services.storage'].get_s3_client = lambda: self.storage_client
        self.modules['src.services.storage'].get_object_bytes = self.read
        self.modules['src.services.storage'].key_from_public_url = lambda _: self.prefix + 'image.png'

        @contextmanager
        def scope(prefix):
            self.prefix = prefix
            yield
        self.modules['src.services.image'].image_storage_scope = scope
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.send_patcher = patch.object(httpx.AsyncClient, 'send', new=AsyncMock(return_value=None))
        self.send_patcher.start()

    def tearDown(self):
        self.send_patcher.stop()
        self.patcher.stop()

    def run_probe(self):
        return asyncio.run(probe.probe_inside())

    def test_realistic_result_is_verified_and_removed_once(self):
        self.assertTrue(self.run_probe())
        self.call_llm.assert_awaited_once()
        self.image.assert_awaited_once()
        self.cleanup.assert_awaited_once_with(self.prefix)
        self.assertTrue(self.prefix.startswith('provider-cutover-check/'))

    def test_failures_and_cleanup_cannot_claim_success(self):
        good_image = self.read.return_value
        self.read.return_value = (b'not an image', 'image/png')
        self.assertFalse(self.run_probe())
        self.cleanup.assert_awaited_once()
        self.read.return_value = good_image
        self.cleanup.return_value = ['failed']
        self.assertFalse(self.run_probe())

    def test_remaining_temp_object_prevents_success(self):
        self.storage_client.list_objects_v2 = lambda **_: {'IsTruncated': False, 'Contents': [{'Key': 'leftover'}]}
        self.assertFalse(self.run_probe())

    def test_budget_blocks_retry_and_unexpected_endpoint(self):
        async def check():
            async with httpx.AsyncClient() as client:
                good = httpx.Request('POST', 'https://api.openai.com/v1/responses',
                                     json={'model': 'gpt-5.6-sol', 'max_output_tokens': 4160})
                other = httpx.Request('POST', 'https://api.openai.com/v1/other', json={})
                with probe._provider_request_budget():
                    await client.send(good)
                    with self.assertRaises(RuntimeError):
                        await client.send(good)
                    with self.assertRaises(RuntimeError):
                        await client.send(other)
        asyncio.run(check())

    def test_no_image_on_bad_text_or_model(self):
        self.text = '{}'
        self.assertFalse(self.run_probe())
        self.image.assert_not_awaited()
        self.settings.image_model = 'unknown'
        self.assertFalse(self.run_probe())
        self.call_llm.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
