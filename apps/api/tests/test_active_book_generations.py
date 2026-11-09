import pytest

from src.models.db import ChildProfile, Job


@pytest.mark.asyncio
async def test_active_generation_discovery_is_scoped_and_excludes_edits_and_terminal_jobs(
    client, db_session, user_key, headers,
):
    other_owner = "a5436321-ecca-4d47-a238-4c075920c859"
    db_session.add_all([
        ChildProfile(id="profile-a", user_key=user_key, name="A"),
        ChildProfile(id="profile-b", user_key=user_key, name="B"),
        ChildProfile(id="foreign-profile", user_key=other_owner, name="C"),
    ])
    for job_id, owner, profile, status, progress in [
        ("job_original", user_key, "profile-a", "running", 72),
        ("series_next", user_key, "profile-a", "queued", 0),
        ("job_legacy", user_key, None, "running", 10),
        ("job_sibling", user_key, "profile-b", "running", 55),
        ("job_foreign", other_owner, "foreign-profile", "queued", 0),
        ("job_finished", user_key, "profile-a", "done", 100),
        ("job_failed", user_key, "profile-a", "failed", 20),
        ("jobXnot_a_generation", user_key, "profile-a", "running", 20),
        ("regen_edit", user_key, "profile-a", "running", 20),
        ("audio_narration", user_key, "profile-a", "running", 20),
    ]:
        db_session.add(Job(id=job_id, user_key=owner, profile_id=profile,
                           status=status, progress=progress))
    await db_session.commit()

    path = "/v1/books/active-generations"
    scoped_headers = {**headers, "X-Profile-Id": "profile-a"}
    response = await client.get(path, headers=scoped_headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert {row["job_id"]: row for row in response.json()} == {
        "job_original": {"job_id": "job_original", "status": "running", "progress": 72},
        "series_next": {"job_id": "series_next", "status": "queued", "progress": 0},
        "job_legacy": {"job_id": "job_legacy", "status": "running", "progress": 10},
    }
    status = await client.get("/v1/books/job_original", headers=scoped_headers)
    assert status.status_code == 200 and status.json()["progress"] == 72
    account_view = await client.get(path, headers=headers)
    assert {row["job_id"] for row in account_view.json()} == {
        "job_original", "series_next", "job_legacy", "job_sibling",
    }
    denied = await client.get(path, headers={**headers, "X-Profile-Id": "foreign-profile"})
    assert denied.status_code == 400
