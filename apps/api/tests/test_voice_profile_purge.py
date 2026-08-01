"""S1: 음성 프로필 단건 삭제·동의 철회가 S3 오디오 샘플을 실제로 파기해야 한다.

가족 음성은 biometric-adjacent PII다. 형제 경로(계정 삭제 users.py, 캐릭터 단건 삭제
characters.py)는 스토리지를 파기하는데 음성 프로필 단건 삭제만 DB 행만 지웠다 —
사용자는 지워졌다고 인지하지만 만료 없는 공개 URL의 오디오 객체는 영구 잔존(PIPA/GDPR).

동의 철회(revoke-consent / PATCH consented=false)는 삭제보다 더 강한 파기 트리거인데
provider_voice_id만 지우고 원본 오디오를 남겼다 — '철회=파기' 약속 위반.

false-green 방지: 엔드포인트는 실경로로 통과시키고 spy는 최하위 외부 경계(storage
delete_keys)에만. 파기 '호출 여부'가 아니라 **역산된 키가 실제 파기 목록에 들어갔는지**를
검증한다.
"""

import uuid

import pytest

from src.core.config import settings

USER = "550e8400-e29b-41d4-a716-446655440000"
HEADERS = {"X-User-Key": USER}


def _sample_url(name: str) -> str:
    """업로드 경로(voice-samples/{user_key}/...)와 같은 형식의 공개 URL."""
    base = (settings.s3_public_url or "").rstrip("/")
    return f"{base}/voice-samples/{USER}/{name}.m4a"


def _expected_key(name: str) -> str:
    return f"voice-samples/{USER}/{name}.m4a"


@pytest.fixture
def delete_spy(monkeypatch):
    """최하위 스토리지 경계만 대체 — 파기 대상 키를 수집한다."""
    from src.routers import voice_profiles as vp

    state = {"keys": [], "fail": []}

    async def fake_delete_keys(keys):
        state["keys"].extend(keys)
        return list(state["fail"])

    monkeypatch.setattr(vp, "delete_keys", fake_delete_keys, raising=False)
    return state


async def _create_profile(client, name: str) -> str:
    res = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "엄마 목소리",
            "relationship": "mother",
            "sample_audio_url": _sample_url(name),
            "consented": True,
        },
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


# ───────────────────────── 단건 삭제 ─────────────────────────


@pytest.mark.asyncio
async def test_delete_voice_profile_purges_audio_sample(client, delete_spy):
    """DELETE는 DB 행뿐 아니라 녹음 오디오까지 파기해야 한다."""
    name = f"del-{uuid.uuid4().hex[:6]}"
    profile_id = await _create_profile(client, name)

    res = await client.delete(f"/v1/voice-profiles/{profile_id}", headers=HEADERS)
    assert res.status_code == 200, res.text

    assert _expected_key(name) in delete_spy["keys"], (
        "가족 음성(PII)이 삭제 후에도 스토리지에 잔존한다"
    )


@pytest.mark.asyncio
async def test_delete_surfaces_storage_failure_as_partial(client, delete_spy):
    """파기 실패를 조용히 삼키지 않고 status=partial + 실패키로 표면화(H8 계약)."""
    name = f"fail-{uuid.uuid4().hex[:6]}"
    profile_id = await _create_profile(client, name)
    delete_spy["fail"] = [_expected_key(name)]

    res = await client.delete(f"/v1/voice-profiles/{profile_id}", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "partial", "파기 실패가 success로 위장되면 잔존을 관측 못 한다"
    assert _expected_key(name) in body.get("failed_keys", [])


@pytest.mark.asyncio
async def test_delete_without_our_bucket_url_does_not_crash(client, delete_spy):
    """외부(우리 버킷 아님) URL이면 역산 불가 — 파기 시도 없이 정상 삭제."""
    res = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "외부 링크",
            "sample_audio_url": "https://other.example.com/x.m4a",
            "consented": True,
        },
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    profile_id = res.json()["id"]

    res = await client.delete(f"/v1/voice-profiles/{profile_id}", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "success"
    assert delete_spy["keys"] == []


# ───────────────────────── 동의 철회 ─────────────────────────


@pytest.mark.asyncio
async def test_revoke_consent_purges_audio_sample(client, delete_spy):
    """동의 철회는 삭제보다 강한 파기 트리거 — 원본 오디오를 남기면 안 된다."""
    name = f"rev-{uuid.uuid4().hex[:6]}"
    profile_id = await _create_profile(client, name)

    res = await client.post(
        f"/v1/voice-profiles/{profile_id}/revoke-consent", headers=HEADERS
    )
    assert res.status_code == 200, res.text

    assert _expected_key(name) in delete_spy["keys"], (
        "동의 철회 후에도 가족 음성 원본이 스토리지에 잔존한다(PIPA 철회-파기 의무)"
    )


@pytest.mark.asyncio
async def test_patch_consented_false_purges_audio_sample(client, delete_spy):
    """PATCH consented=false도 동일한 철회 의미 — 같은 파기 계약."""
    name = f"patch-{uuid.uuid4().hex[:6]}"
    profile_id = await _create_profile(client, name)

    res = await client.patch(
        f"/v1/voice-profiles/{profile_id}",
        json={"consented": False},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text

    assert _expected_key(name) in delete_spy["keys"]


@pytest.mark.asyncio
async def test_patch_unrelated_field_does_not_purge(client, delete_spy):
    """라벨 변경 같은 무관한 수정이 오디오를 지우면 안 된다(과잉 파기 방지)."""
    name = f"keep-{uuid.uuid4().hex[:6]}"
    profile_id = await _create_profile(client, name)

    res = await client.patch(
        f"/v1/voice-profiles/{profile_id}",
        json={"label": "아빠 목소리"},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    assert delete_spy["keys"] == []
