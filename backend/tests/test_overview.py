from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.main import app
from app.models import Asset, CostEntry, Project, Task
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
