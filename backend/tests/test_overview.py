from uuid import uuid4
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.main import app
from app.models import Asset, CostEntry, Project, Task, now
from test_postgres import database


def test_overview_uses_project_scoped_records_and_currency_totals(database, monkeypatch):
    monkeypatch.setenv('AI_STORY_ENABLE_PAID_TEXT', '0')
    client = TestClient(app)
    with database.begin() as db:
        current = Project(name='V3 总览验收')
        other = Project(name='项目边界')
        db.add_all([current, other])
        db.flush()
        project_id, other_id = current.id, other.id
        cover = Asset(project_id=project_id, name='参考图.PNG', storage_key=f'originals/{uuid4()}.png',
                      sha256='9'*64, size_bytes=100, authorization='测试记录')
        db.add(cover)
        db.flush()
        cover_id = cover.id
        rendered = Task(project_id=project_id, kind='render', status='succeeded', idempotency_key='overview-render',
                        output={'storage_key':'outputs/verified.mp4','width':640,'height':360,'duration':1.25})
        external = Task(project_id=other_id, kind='render', status='succeeded', idempotency_key='other-render',
                        output={'storage_key':'outputs/another.mp4'})
        db.add_all([rendered, external, Task(project_id=project_id, kind='probe', status='queued', idempotency_key='probe')])
        db.flush()
        rendered_id = rendered.id
        for currency, cents in [('CNY', 125), ('USD', 12)]:
            db.add(CostEntry(project_id=project_id, task_id=rendered.id, provider='test-ledger',
                            amount_cents=cents, currency=currency, reference=str(uuid4())))
    try:
        result = client.get(f'/api/projects/{project_id}/overview')
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['asset_count'] == 1 and data['cover']['id'] == cover_id
        assert data['task_counts'] == {'queued': 1, 'succeeded': 1}
        assert data['render_count'] == 1 and data['recent_renders'][0]['id'] == rendered_id
        assert 'storage_key' not in data['recent_renders'][0]
        assert data['costs'] == [
            {'currency': 'CNY', 'amount_micros': '1250000', 'unknown': 0},
            {'currency': 'USD', 'amount_micros': '120000', 'unknown': 0},
        ]
        assert data['draft_review_count'] == 0 and data['latest_run'] is None and data['live_authorized'] is False
        assert client.get(f'/api/projects/{uuid4()}/overview').status_code == 404
    finally:
        with database.begin() as db:
            db.execute(delete(CostEntry).where(CostEntry.project_id == project_id))
            db.execute(delete(Task).where(Task.project_id.in_([project_id, other_id])))
            db.execute(delete(Asset).where(Asset.project_id == project_id))
            db.execute(delete(Project).where(Project.id.in_([project_id, other_id])))


def test_task_views_filter_before_pagination_and_keep_project_boundary(database):
    client = TestClient(app)
    with database.begin() as db:
        project, other = Project(name='Queue views'), Project(name='Another project')
        db.add_all([project, other])
        db.flush()
        project_id, other_id = project.id, other.id
        start = now()
        specifications = [
            (project_id, 'render', 'succeeded', {'storage_key': 'outputs/old.mp4'}),
            (project_id, 'timeline_render', 'succeeded', {'storage_key': 'outputs/new.mp4'}),
            (project_id, 'render', 'succeeded', {}),
            (project_id, 'probe', 'running', {}),
            (project_id, 'probe', 'queued', {}),
            (project_id, 'render', 'failed', {}),
            (project_id, 'analyze', 'cancelled', {}),
            (other_id, 'render', 'succeeded', {'storage_key': 'outputs/other.mp4'}),
        ]
        rows = [Task(project_id=owner, kind=kind, status=status, output=output,
                     idempotency_key=f'queue-test:{i}', created_at=start + timedelta(seconds=i))
                for i, (owner, kind, status, output) in enumerate(specifications)]
        db.add_all(rows)
        db.flush()
        ids = [item.id for item in rows]
    try:
        path = f'/api/projects/{project_id}/tasks'
        def ids_for(**query):
            response = client.get(path, params=query)
            assert response.status_code == 200, response.text
            return [row['id'] for row in response.json()]
        assert ids_for(limit=2) == [ids[6], ids[5]]
        assert ids_for(view='renders', limit=1) == [ids[1]]
        assert ids_for(view='renders', limit=1, offset=1) == [ids[0]]
        assert ids_for(view='renders', limit=1, offset=2) == []
        assert ids_for(view='active') == [ids[4], ids[3]]
        assert ids_for(view='issues') == [ids[6], ids[5]]
        assert ids_for(view='completed') == [ids[2], ids[1], ids[0]]
    finally:
        with database.begin() as db:
            db.execute(delete(Task).where(Task.project_id.in_([project_id, other_id])))
            db.execute(delete(Project).where(Project.id.in_([project_id, other_id])))
