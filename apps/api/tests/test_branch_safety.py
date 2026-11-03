"""Branch access must follow the same account/profile boundary as books."""
import pytest

from src.models.db import Book, ChildProfile, Job


@pytest.mark.asyncio
async def test_branch_profile_isolation_and_unassigned_book_access(client, headers, db_session):
    user = headers['X-User-Key']
    db_session.add_all([
        ChildProfile(id='branch-profile-a', user_key=user, name='Profile A'),
        ChildProfile(id='branch-profile-b', user_key=user, name='Profile B'),
        Job(id='branch-profile-job', status='done', user_key=user),
        Job(id='branch-shared-job', status='done', user_key=user),
    ])
    await db_session.flush()
    db_session.add_all([
        Book(id='branch-profile-book', job_id='branch-profile-job', title='Book',
             language='ko', target_age='5-7', style='watercolor', user_key=user,
             profile_id='branch-profile-a', cover_image_url=''),
        Book(id='branch-shared-book', job_id='branch-shared-job', title='Shared',
             language='ko', target_age='5-7', style='watercolor', user_key=user,
             cover_image_url=''),
    ])
    await db_session.commit()
    nodes = {'nodes': [{'node_key': 'start', 'page_number': 1, 'text': 'Story', 'options': []}]}
    a = {**headers, 'X-Profile-Id': 'branch-profile-a'}
    b = {**headers, 'X-Profile-Id': 'branch-profile-b'}
    invalid = {**headers, 'X-Profile-Id': 'not-owned'}
    path = '/v1/branch/books/branch-profile-book'
    assert (await client.post(f'{path}/initialize', json=nodes, headers=a)).status_code == 200
    assert (await client.get(f'{path}/graph', headers=a)).status_code == 200
    assert (await client.post(f'{path}/choose', json={'current_node_key': 'start',
                                                     'option_text': 'anything'}, headers=a)).status_code == 200
    assert (await client.get(f'{path}/graph', headers=b)).status_code == 403
    assert (await client.post(f'{path}/initialize', json={**nodes, 'overwrite': True}, headers=b)).status_code == 403
    assert (await client.post(f'{path}/choose', json={'current_node_key': 'start',
                                                     'option_text': 'anything'}, headers=b)).status_code == 403
    assert (await client.get(f'{path}/graph', headers=invalid)).status_code == 400
    graph = await client.get(f'{path}/graph', headers=a)
    assert graph.json()['nodes'][0]['text'] == 'Story'
    shared = '/v1/branch/books/branch-shared-book'
    assert (await client.post(f'{shared}/initialize', json=nodes, headers=b)).status_code == 200
    assert (await client.get(f'{shared}/graph', headers=a)).status_code == 200
