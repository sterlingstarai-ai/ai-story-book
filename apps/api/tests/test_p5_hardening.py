from pathlib import Path

import pytest

import src.main as main_module
from src.core.config import API_ENV_FILE, Settings
from src.models.db import Book, Job, Page
from src.services.iap_verifier import iap_verifier


@pytest.mark.asyncio
async def test_live_health_endpoint_reports_alive(client):
    response = await client.get('/health/live')

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'alive'
    assert 'version' in body


@pytest.mark.asyncio
async def test_ready_health_endpoint_returns_503_for_degraded_status(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _fake_payload(*, include_metrics: bool):
        assert include_metrics is False
        return {
            'status': 'degraded',
            'version': 'test',
            'services': {
                'database': 'healthy',
                'redis': 'unhealthy',
                'job_monitor': 'healthy',
            },
        }

    monkeypatch.setattr(main_module, '_build_readiness_payload', _fake_payload)

    response = await client.get('/health/ready')

    assert response.status_code == 503
    body = response.json()
    assert body['status'] == 'degraded'
    assert body['services']['redis'] == 'unhealthy'


@pytest.mark.asyncio
async def test_book_status_and_detail_include_degraded_asset_metadata(
    client,
    db_session,
    headers: dict,
):
    user_key = headers['X-User-Key']
    job = Job(
        id='job-p5-degraded',
        status='done',
        progress=100,
        current_step='완료',
        user_key=user_key,
    )
    book = Book(
        id='book-p5-degraded',
        job_id=job.id,
        title='테스트 동화',
        language='ko',
        target_age='5-7',
        style='watercolor',
        theme='우정',
        cover_image_url='https://placeholder.invalid/cover.png',
        user_key=user_key,
    )
    pages = [
        Page(
            book_id=book.id,
            page_number=1,
            text='첫 페이지',
            image_url='https://placeholder.invalid/page-1.png',
            audio_url=None,
        ),
        Page(
            book_id=book.id,
            page_number=2,
            text='둘째 페이지',
            image_url='https://cdn.example.com/page-2.png',
            audio_url_ko='https://cdn.example.com/page-2-ko.mp3',
        ),
    ]
    db_session.add(job)
    db_session.add(book)
    db_session.add_all(pages)
    await db_session.commit()

    status_response = await client.get(f'/v1/books/{job.id}', headers=headers)
    assert status_response.status_code == 200
    status_body = status_response.json()
    result = status_body['result']

    assert result['generation_warnings'] == [
        {
            'code': 'cover_placeholder_image',
            'message': '표지 이미지 생성이 실패해 임시 이미지를 표시하고 있습니다.',
            'asset': 'cover',
            'page_number': 0,
        },
        {
            'code': 'page_placeholder_image',
            'message': '일부 페이지 이미지 생성이 실패해 임시 이미지를 표시하고 있습니다.',
            'asset': 'image',
            'page_number': 1,
        },
    ]
    assert result['pages'][0]['asset_status']['image']['state'] == 'degraded'
    assert result['pages'][0]['asset_status']['audio']['state'] == 'missing'
    assert result['pages'][1]['asset_status']['image']['state'] == 'generated'
    assert result['pages'][1]['asset_status']['audio']['state'] == 'available'

    detail_response = await client.get(f'/v1/books/{book.id}/detail', headers=headers)
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body['generation_warnings'] == result['generation_warnings']
    assert detail_body['pages'][0]['asset_status'] == result['pages'][0]['asset_status']


def test_settings_are_scoped_to_apps_api_env_and_ignore_extra_input():
    assert API_ENV_FILE == Path(__file__).resolve().parents[1] / '.env'
    assert API_ENV_FILE.parent.name == 'api'

    settings = Settings(
        database_url='sqlite+aiosqlite:///./test.db',
        redis_url='redis://localhost:6379/0',
        unexpected_key='ignored',
    )

    assert settings.database_url == 'sqlite+aiosqlite:///./test.db'
    assert settings.redis_url == 'redis://localhost:6379/0'


@pytest.mark.asyncio
async def test_iap_verifier_local_and_hybrid_modes_are_explicit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_module.settings, 'iap_verification_mode', 'local')
    monkeypatch.setattr(main_module.settings, 'google_play_package_name', None)
    monkeypatch.setattr(main_module.settings, 'google_play_access_token', None)

    local_result = await iap_verifier.verify_purchase(
        platform='google',
        product_id='credit_pack_1',
        transaction_id='local-mode-tx',
        purchase_token='purchase-token',
    )
    assert local_result.verified is True
    assert local_result.source == 'local_google'

    monkeypatch.setattr(main_module.settings, 'iap_verification_mode', 'hybrid')
    monkeypatch.setattr(main_module.settings, 'google_play_package_name', 'com.example.storybook')
    monkeypatch.setattr(
        iap_verifier,
        '_resolve_google_access_token',
        lambda: 'hybrid-access-token',
    )

    async def _raise_validation_error(**kwargs):
        from src.core.exceptions import ValidationError

        raise ValidationError('store lookup failed')

    monkeypatch.setattr(iap_verifier, '_fetch_google_purchase', _raise_validation_error)

    hybrid_result = await iap_verifier.verify_purchase(
        platform='google',
        product_id='credit_pack_1',
        transaction_id='hybrid-mode-tx',
        purchase_token='purchase-token',
    )
    assert hybrid_result.verified is True
    assert hybrid_result.source == 'local_google_hybrid_fallback'
