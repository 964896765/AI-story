from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.main import app
from app.models import Project
from test_postgres import database


def test_project_spec_versions_isolation_and_conflict(database):
    client = TestClient(app)
    with database.begin() as db:
        projects = [Project(name='spec versions'),Project(name='another project')]
        db.add_all(projects)
        db.flush()
        project,other = [item.id for item in projects]
    root = f'/api/projects/{project}/production-specs'
    foreign = f'/api/projects/{other}/production-specs'
    settings = {'episode_count':1,'episode_duration_ms':1500,'style':'线稿','fps':24,
                'profile':'square','width':720,'height':720,'platform':'local-test','region':'CN',
                'budget_cents':0,'imported_note':'旧浏览器备注，仅保存在规格记录'}
    try:
        draft = client.post(root,json={'expected_version':0,'idempotency_key':'draft','settings':{}})
        assert draft.status_code==201 and draft.json()['missing_fields']
        assert client.get(foreign).json()['items']==[]
        assert client.get(foreign+'/'+draft.json()['id']).status_code==404
        assert client.get(foreign+'/compare',params={'left':draft.json()['id'],'right':draft.json()['id']}).status_code==404
        editions = [{**settings,'style':style} for style in ['线稿甲','线稿乙']]

        def save(index):
            return client.post(root,json={'expected_version':1,'idempotency_key':str(index),'settings':editions[index]})

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save,range(2)))
        assert sorted(item.status_code for item in results)==[201,409]
        first = next(item.json() for item in results if item.status_code==201)
        assert not first['missing_fields'] and not first['compatibility_errors']
        assert save(next(index for index,item in enumerate(editions) if item['style']==first['settings']['style'])).json()==first
        modified = client.post(root,json={'expected_version':2,'idempotency_key':'update','settings':{**settings,'fps':30}}).json()
        assert modified['compatibility_errors']
        assert modified['sha256']!=first['sha256']
        diff = client.get(root+'/compare',params={'left':first['id'],'right':modified['id']}).json()
        assert '渲染' in diff['affected_modules'] and 'Guardian' in diff['affected_modules']
        restored = client.post(root+'/restore',json={'expected_version':3,'idempotency_key':'restore','source_version_id':first['id']}).json()
        assert restored['id']!=first['id'] and restored['version']==4
        assert restored['settings']==first['settings'] and restored['sha256']==first['sha256']
        assert restored['restored_from_id']==first['id']
        assert client.get(root+'/'+first['id']).json()==first
        assert client.post(foreign+'/restore',json={'expected_version':0,'idempotency_key':'bad','source_version_id':first['id']}).status_code==404
    finally:
        with database.begin() as db:
            db.execute(delete(Project).where(Project.id.in_([project,other])))
