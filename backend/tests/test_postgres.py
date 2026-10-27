"""Opt in using TEST_DATABASE_URL pointing to a disposable migrated PostgreSQL DB."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import session
from app import worker
from app.models import TaskEvent, Task, Asset, Project, now
from datetime import timedelta

@pytest.fixture
def database(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL not configured; PostgreSQL integration not verified')
    engine = create_engine(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[session] = dependency
    monkeypatch.setattr(worker, 'Session', factory)
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()

def test_project_asset_worker_and_retry(database, tmp_path, monkeypatch):
    from app import storage
    import subprocess
    client = TestClient(app)
    video = tmp_path / 'fixture.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=size=160x120:rate=10','-t','1','-c:v','mpeg4',str(video)], check=True, timeout=30)
    monkeypatch.setattr(storage, 'resolve_key', lambda key: tmp_path / key)
    monkeypatch.setattr(worker, 'resolve_key', lambda key: tmp_path / key)
    p = client.post('/api/projects', json={'name':'集成验收 ' + str(uuid4())})
    assert p.status_code == 201
    project_id = p.json()['id']
    try:
        a = client.post(f'/api/projects/{project_id}/assets', files={'file':('fixture.mp4',video.read_bytes(),'video/mp4')},data={'authorization':'本项目 FFmpeg 自行生成测试视频'})
        assert a.status_code == 201, a.text
        asset_id = a.json()['id']
        assert a.json()['size_bytes'] == len(video.read_bytes())
        body = {'asset_id':asset_id,'idempotency_key':'probe-v1'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:client.post(f'/api/projects/{project_id}/tasks',json=body), range(2)))
        assert all(r.status_code == 201 for r in results)
        task_id = results[0].json()['id']
        assert results[1].json()['id'] == task_id
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker.run_once(), range(2)))
        tasks = client.get(f'/api/projects/{project_id}/tasks').json()
        assert len(tasks) == 1 and tasks[0]['status'] == 'succeeded' and tasks[0]['attempt'] == 1
        assert client.post(f'/api/tasks/{task_id}/retry').status_code == 409
        bad = client.post(f'/api/projects/{project_id}/assets',files={'file':('bad.mp4',b'bad')},data={'authorization':'测试无效文件'})
        bad_task = client.post(f'/api/projects/{project_id}/tasks',json={'asset_id':bad.json()['id'],'idempotency_key':'bad'}).json()
        worker.run_once()
        assert client.get(f'/api/projects/{project_id}/tasks').json()[0]['status'] == 'failed'
        assert client.post(f"/api/tasks/{bad_task['id']}/retry").status_code == 200
        worker.run_once()
        events = client.get(f"/api/tasks/{bad_task['id']}/events").json()
        assert max(e['attempt'] for e in events) == 2
        with database.begin() as db:
            stale = db.get(Task, bad_task['id'])
            stale.status = 'running'
            stale.lease_until = now() - timedelta(seconds=1)
        worker.run_once()
        with database() as db:
            stale = db.get(Task, bad_task['id'])
            assert stale.status == 'failed' and 'lease expired' in stale.error
        conflict = client.post(f'/api/projects/{project_id}/tasks', json={'asset_id':bad.json()['id'], 'idempotency_key':'probe-v1'})
        assert conflict.status_code == 409
    finally:
        with database.begin() as db:
            ids = select(Task.id).where(Task.project_id == project_id)
            db.execute(delete(TaskEvent).where(TaskEvent.task_id.in_(ids)))
            db.execute(delete(Task).where(Task.project_id == project_id))
            db.execute(delete(Asset).where(Asset.project_id == project_id))
            db.execute(delete(Project).where(Project.id == project_id))
