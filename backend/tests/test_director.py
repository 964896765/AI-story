from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from app import worker
from app.models import Asset, DirectorPlan
from test_creative import creative
from test_delivery import delivery_fixture
from test_postgres import database
from test_production import series_fixture
from test_render_postgres import studio


@pytest.fixture
def director(delivery_fixture):
    fixture = delivery_fixture
    _, project, *_, factory = fixture[0]
    yield fixture
    with factory.begin() as db:
        db.execute(delete(DirectorPlan).where(DirectorPlan.project_id == project))


def test_director_render_approval_is_atomic_and_idempotent(director):
    studio, _, prep, timeline = director
    client, project, video, _, _, task, resolve, factory = studio
    fixed = timeline(prep(1), 1)['timeline_version_id']
    root = f'/api/director/projects/{project}/plans'
    body = {'instruction': '渲染已核对时间轴', 'operation': {'action': 'render', 'version_id': fixed},
            'idempotency_key': 'director-render'}
    created = client.post(root, json=body)
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan['task'] is None and plan['approved_at'] is None and plan['external_cost_cents'] == 0
    assert client.post(root, json=body).json() == plan
    assert client.post(root, json={**body, 'instruction': '冲突'}).status_code == 409
    assert client.get(f'/api/projects/{project}/tasks').json() == []
    other = client.post('/api/projects', json={'name': '隔离项目 ' + str(uuid4())}).json()['id']
    foreign = root.replace(project, other)
    assert client.post(foreign, json=body).status_code == 422
    assert client.get(f"{foreign}/{plan['id']}").status_code == 404
    path = f"{root}/{plan['id']}"
    assert client.post(f"{foreign}/{plan['id']}/execute").status_code == 404
    with factory.begin() as db:
        db.execute(update(Asset).where(Asset.id == video['id']).values(version=2))
    assert client.post(path + '/execute').status_code == 409
    assert client.get(path).json()['task'] is None
    assert client.get(f'/api/projects/{project}/tasks').json() == []
    fresh = client.post(root, json={**body, 'idempotency_key': 'updated-snapshot'}).json()
    path = f"{root}/{fresh['id']}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path + '/execute'), range(2)))
    assert all(reply.status_code == 200 for reply in responses)
    first, second = [reply.json() for reply in responses]
    assert first == second and first['approved_at']
    job = first['task']['id']
    assert worker.run_once()
    result = client.get(path).json()
    assert result['task']['status'] == 'succeeded', result
    assert result['task']['progress'] == 100
    recorded = task(job)
    assert recorded['story_version_id'] == fixed
    assert resolve(recorded['output']['storage_key']).is_file()
    media = client.get(f'/api/tasks/{job}/output', headers={'Range': 'bytes=0-31'})
    assert media.status_code == 206
    assert client.post(path + '/execute').json() == result
    assert len(client.get(f'/api/projects/{project}/tasks').json()) == 1


def test_director_package_checks_rights_at_prepare_and_execute(director):
    studio, production, prep, timeline = director
    client, project, video, _, _, task, _, _ = studio
    source = prep(1)
    batch = client.post(production, json={'plan_version_id': source, 'timelines': [timeline(source, 1)],
                                          'idempotency_key': 'director-package-batch'}).json()
    root = f'/api/director/projects/{project}/plans'
    body = {'instruction': '交付授权样片', 'idempotency_key': 'deliver-one', 'operation': {
        'action': 'release', 'run_id': batch['id'], 'title': '海港交付包', 'platform': 'local-test', 'region': 'CN'}}
    assert client.post(root, json=body).status_code == 409
    assert worker.run_once() and worker.run_once()
    assert client.post(root, json=body).status_code == 409
    grant = {'status': 'approved', 'source_type': 'owned', 'holder': '原创验收样片',
             'evidence': '本地生成，仅验收', 'commercial': True, 'regions': ['CN'], 'platforms': ['local-test']}
    rights = f"/api/library/assets/{video['id']}/rights"
    assert client.post(rights, json={**grant, 'idempotency_key': 'first-right'}).status_code == 201
    pending = client.post(root, json=body)
    assert pending.status_code == 201, pending.text
    assert pending.json()['task'] is None
    replacement = {**grant, 'holder': '第二版权利记录', 'idempotency_key': 'second-right'}
    assert client.post(rights, json=replacement).status_code == 201
    assert client.post(f"{root}/{pending.json()['id']}/execute").status_code == 409
    assert client.get(f'/api/delivery/projects/{project}/packages').json() == []
    fresh = client.post(root, json={**body, 'idempotency_key': 'deliver-reviewed-again'}).json()
    executed = client.post(f"{root}/{fresh['id']}/execute")
    assert executed.status_code == 200, executed.text
    job = executed.json()['task']['id']
    assert worker.run_once()
    result = client.get(f"{root}/{fresh['id']}").json()
    assert result['task']['status'] == 'succeeded', result
    downloaded = client.get(f'/api/delivery/packages/{job}/file')
    assert downloaded.status_code == 200
    assert sha256(downloaded.content).hexdigest() == task(job)['output']['sha256']
