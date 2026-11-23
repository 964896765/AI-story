from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import model_connections
from app.main import app
from app.models import ModelConnectionDraft
from test_postgres import database


def test_connection_drafts_are_saved_but_cannot_execute(database, monkeypatch):
    monkeypatch.setattr(model_connections.shutil, 'which', lambda command: 'test-codex-path' if command == 'codex' else None)
    client = TestClient(app)
    route = '/api/models/connections'
    try:
        status = client.get(route).json()
        assert status['codex_cli_detected'] is True
        assert status['execution_enabled'] is False
        assert 'test-codex-path' not in str(status)
        codex = client.post(route+'/codex', json={'model': 'codex-preference'})
        assert codex.status_code == 200
        assert client.post(route+'/codex', json={'model': 'codex-preference', 'region': 'CN'}).status_code == 422
        payload = {'model': 'video-model', 'base_url': 'https://example.test/v1/', 'secret_env': 'TEST_VIDEO_API_KEY'}
        for invalid in ({'secret_env': 'secret-value-not-for-output'}, {'base_url': 'https://localhost/v1'},
                        {'base_url': 'https://example.test/v1?api_key=secret-value-not-for-output'}, {'enabled': True}):
            response = client.post(route+'/wan-video', json={**payload, **invalid})
            assert response.status_code == 422
            assert 'secret-value-not-for-output' not in response.text
        assert client.post(route+'/wan-video', json=payload).status_code == 200
        update = client.post(route+'/wan-video', json={**payload, 'model': 'updated-video'})
        assert update.status_code == 200
        assert update.json()['execution_enabled'] is False
        saved = client.get(route).json()['drafts']
        assert saved['codex']['model'] == 'codex-preference'
        assert saved['wan-video'] == {**payload, 'model': 'updated-video', 'base_url': 'https://example.test/v1', 'region': ''}
        with database() as db:
            assert len(db.scalars(select(ModelConnectionDraft)).all()) == 2
    finally:
        with database.begin() as db:
            db.execute(delete(ModelConnectionDraft))
