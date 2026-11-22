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


def test_director_batch_and_scoped_rework_keep_reviewed_inputs(director):
    studio, production, prep, timeline = director
    client, project, asset, _, _, task, resolve, _ = studio
    source = prep(2)
    initial = [timeline(source, 1), timeline(source, 2)]
    base = f'/api/director/projects/{project}'
    root = base + '/plans'
    assert [row['version_id'] for row in client.get(base + '/batch-options').json()] == [source]
    options = client.get(f'{base}/batch-options/{source}').json()
    assert {row['version_id'] for row in options['timelines']} == {row['timeline_version_id'] for row in initial}
    operation = {'action': 'batch', 'plan_version_id': source, 'timelines': initial,
                 'policy': {'require_audio': True}}
    body = {'instruction': '按固定计划制片', 'idempotency_key': 'initial-batch', 'operation': operation}
    incomplete = {**body, 'operation': {**operation, 'timelines': initial[:1]}}
    assert client.post(root, json=incomplete).status_code == 422
    prepared = client.post(root, json=body)
    assert prepared.status_code == 201, prepared.text
    plan = prepared.json()
    assert [row['mode'] for row in plan['preview']] == ['render', 'render']
    assert plan['approved_at'] is None and plan['run_id'] is None
    assert client.get(production).json() == []
    assert client.get(f'/api/projects/{project}/tasks').json() == []
    execute = f"{root}/{plan['id']}/execute"
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: client.post(execute), range(2)))
    assert all(reply.status_code == 200 for reply in replies)
    batch_id = replies[0].json()['run_id']
    assert replies[1].json()['run_id'] == batch_id
    assert len(client.get(production).json()) == 1
    assert len(client.get(f'/api/projects/{project}/tasks').json()) == 4
    assert all(worker.run_once() for _ in range(4))
    completed = client.get(f"{root}/{plan['id']}").json()['run']
    assert completed['status'] == 'passed'
    assert all(resolve(task(item['render_task_id'])['output']['storage_key']).is_file()
               for item in completed['episodes'])

    changed = timeline(source, 2, frames=26)
    repair = {**body, 'idempotency_key': 'partial-rework', 'operation': {
        **operation, 'previous_run_id': batch_id, 'timelines': [changed]}}
    draft = client.post(root, json=repair)
    assert draft.status_code == 201, draft.text
    assert [row['mode'] for row in draft.json()['preview']] == ['reuse', 'render']
    pending_path = f"{root}/{draft.json()['id']}/execute"
    old_render = task(completed['episodes'][0]['render_task_id'])
    output = resolve(old_render['output']['storage_key'])
    original = output.read_bytes()
    output.write_bytes(b'damaged locally')
    assert client.post(pending_path).status_code == 409
    assert client.get(production).json()[0]['id'] == batch_id
    output.write_bytes(original)
    response = client.post(pending_path)
    assert response.status_code == 200, response.text
    assert all(worker.run_once() for _ in range(2))
    rework = client.get(f"{root}/{draft.json()['id']}").json()['run']
    assert rework['status'] == 'passed' and rework['previous_run_id'] == batch_id and rework['reused'] == 1
    assert rework['episodes'][0]['render_task_id'] == completed['episodes'][0]['render_task_id']
    assert rework['episodes'][0]['qc_task_id'] == completed['episodes'][0]['qc_task_id']
    assert rework['episodes'][1]['render_task_id'] != completed['episodes'][1]['render_task_id']

    recheck = client.post(root, json={**body, 'idempotency_key': 'recheck-only', 'operation': {
        **operation, 'previous_run_id': rework['id'], 'timelines': [], 'recheck_quality': True}})
    assert recheck.status_code == 201, recheck.text
    assert [row['mode'] for row in recheck.json()['preview']] == ['recheck', 'recheck']
    response = client.post(f"{root}/{recheck.json()['id']}/execute")
    assert response.status_code == 200, response.text
    assert response.json()['run']['rechecked'] == 2
    assert all(worker.run_once() for _ in range(2))
    refreshed = client.get(f"{root}/{recheck.json()['id']}").json()['run']
    assert refreshed['status'] == 'passed'
    assert [row['render_task_id'] for row in refreshed['episodes']] == [
        row['render_task_id'] for row in rework['episodes']]
