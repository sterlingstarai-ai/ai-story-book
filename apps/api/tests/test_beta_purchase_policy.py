"""New purchases are opt-in; disabling them must not disable receipt settlement."""
import pytest

from src.core.config import settings


@pytest.mark.asyncio
async def test_beta_does_not_advertise_new_purchases_even_with_store_keys(client, monkeypatch):
    monkeypatch.setattr(settings, 'purchases_enabled', False)
    monkeypatch.setattr(settings, 'iap_verification_mode', 'strict')
    monkeypatch.setattr(settings, 'apple_iap_shared_secret', 'test-secret')
    monkeypatch.setattr(settings, 'apple_bundle_id', 'com.storybook.aiStoryBook')
    monkeypatch.setattr(settings, 'iap_webhook_secret', 'test-webhook')
    caps = (await client.get('/v1/config/capabilities')).json()
    for field in ('purchases_supported', 'apple_purchases_supported', 'google_purchases_supported'):
        assert caps[field] is False


@pytest.mark.asyncio
async def test_purchase_availability_is_store_specific_and_requires_strict_verification(client, monkeypatch):
    monkeypatch.setattr(settings, 'apple_app_id', 123456)
    monkeypatch.setattr(settings, 'purchases_enabled', True)
    monkeypatch.setattr(settings, 'iap_verification_mode', 'strict')
    monkeypatch.setattr(settings, 'apple_iap_shared_secret', 'test-secret')
    monkeypatch.setattr(settings, 'apple_bundle_id', 'com.storybook.aiStoryBook')
    monkeypatch.setattr(settings, 'iap_webhook_secret', 'test-webhook')
    monkeypatch.setattr(settings, 'google_play_package_name', None)
    caps = (await client.get('/v1/config/capabilities')).json()
    assert caps['purchases_supported'] is True
    assert caps['apple_purchases_supported'] is True
    assert caps['google_purchases_supported'] is False
    monkeypatch.setattr(settings, 'iap_verification_mode', 'local')
    assert (await client.get('/v1/config/capabilities')).json()['purchases_supported'] is False


@pytest.mark.asyncio
async def test_free_beta_readiness_skips_unused_store_keys_but_keeps_strict_requirement(client, monkeypatch):
    monkeypatch.setattr(settings, 'testing', False)
    monkeypatch.setattr(settings, 'purchases_enabled', False)
    monkeypatch.setattr(settings, 'iap_verification_mode', 'strict')
    monkeypatch.setattr(settings, 'apple_iap_shared_secret', None)
    monkeypatch.setattr(settings, 'google_play_package_name', None)
    monkeypatch.setattr(settings, 'iap_webhook_secret', '')
    monkeypatch.setattr(settings, 'admin_api_key', 'test-admin')
    response = await client.get('/health/detailed', headers={'X-Admin-Key': 'test-admin'})
    missing = response.json().get('missing_keys', [])
    assert 'iap_store_credentials_missing' not in missing
    assert 'iap_webhook_secret_missing' not in missing
    monkeypatch.setattr(settings, 'iap_verification_mode', 'hybrid')
    response = await client.get('/health/detailed', headers={'X-Admin-Key': 'test-admin'})
    assert 'iap_mode_not_strict' in response.json()['missing_keys']
