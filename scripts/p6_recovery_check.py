"""Back up the local database and production files, then rehearse the requested migration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def run_alembic(url, *arguments):
    env = {**os.environ, 'DATABASE_URL': url.render_as_string(hide_password=False)}
    subprocess.run([sys.executable, '-m', 'alembic', *arguments],
                   cwd=ROOT / 'backend', env=env, check=True, timeout=45)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_child(root, key):
    child = (root / key).resolve()
    if not child.is_relative_to(root.resolve()) or child == root:
        raise RuntimeError('Unsafe storage reference')
    return child


def manifest(connection, storage, revision, complete=False):
    assets = dict(connection.execute('SELECT storage_key, sha256 FROM assets'))
    tasks = connection.execute('SELECT id, output FROM tasks ORDER BY id').fetchall()
    files = dict(assets)
    for task_id, output in tasks:
        for prefix in ('outputs', 'tmp'):
            folder = safe_child(storage, f'{prefix}/{task_id}')
            if folder.is_dir():
                for entry in folder.rglob('*'):
                    if not entry.is_file():
                        continue
                    verified = safe_child(storage, entry.relative_to(storage))
                    files.setdefault(verified.relative_to(storage).as_posix(), None)
        output = output or {}
        if (key := output.get('storage_key')):
            if key not in files and not safe_child(storage,key).is_file():
                raise RuntimeError(f'Published output missing: {task_id}')
            files[key] = output.get('sha256') or files.get(key)
        if output.get('caption_storage_key'):
            files[output['caption_storage_key']] = output.get('caption_sha256')
        for item in output.get('files', {}).values() if isinstance(output.get('files'), dict) else ():
            files[item['storage_key']] = item['sha256']
    if revision in ('0007','0008','0009','0010','0011','0012','0013','0014','0015'):
        for (payload,) in connection.execute('SELECT payload FROM media_analyses'):
            for artifact in payload['artifacts']:
                files[artifact['storage_key']] = artifact['sha256']
    if complete:
        for root in ('originals', 'outputs', 'analysis'):
            for entry in (storage/root).rglob('*'):
                if entry.is_file():
                    location = safe_child(storage,entry.relative_to(storage)).relative_to(storage).as_posix()
                    files.setdefault(location,None)
    return files, len(assets)

def verify_restored_api(url,path,projects,assets,revision):
    env={**os.environ,'DATABASE_URL':url.render_as_string(hide_password=False),
         'STORAGE_ROOT':str(path),'AI_STORY_ENABLE_PAID_TEXT':'0','AI_STORY_RESTORE_REVISION':revision}
    command = """
from fastapi.testclient import TestClient
from app.main import app
import json, os
with TestClient(app) as client:
    health = client.get('/api/health').json()['checks']
    assert health['database'] and health['ffmpeg'] and health['ffprobe']
    if os.environ['AI_STORY_RESTORE_REVISION'] == '0015':
        assert health['schema']
    projects = client.get('/api/projects').json()
    assets = [asset for project in projects for asset in client.get('/api/projects/'+project['id']+'/assets').json()]
    media = next((asset for asset in assets if asset['name'].lower().endswith(('.mp4','.mkv','.mov','.wav'))),None)
    partial = client.get('/api/assets/'+media['id']+'/media',headers={'Range':'bytes=0-15'}) if media else None
    assert partial is None or (partial.status_code == 206 and len(partial.content) == 16)
    print(json.dumps({'projects':len(projects),'assets':len(assets),'range':partial.status_code if partial else None}))
"""
    result=subprocess.check_output([sys.executable,'-c',command],cwd=ROOT/'backend',env=env,text=True,timeout=35)
    verified=json.loads(result)
    if (verified['projects'],verified['assets'])!=(projects,assets):
        raise RuntimeError('Restored API inventory differs from the recovered database')
    return verified


def snapshot_and_verify(source, storage, container, directory, before, target, complete=False):
    dump = directory / 'database.dump'
    with dump.open('wb') as output:
        subprocess.run(['docker','exec',container,'pg_dump','-U',source.username,'-d',source.database,'-Fc'],
                       stdout=output, check=True, timeout=60)
    db_name = 'story_upgrade_restore_' + uuid4().hex[:12]
    admin = source.set(drivername='postgresql', database='postgres')
    restored = source.set(database=db_name)
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db_name)))
        try:
            with dump.open('rb') as backup:
                subprocess.run(['docker','exec','-i',container,'pg_restore','--exit-on-error','--no-owner',
                                '-U',source.username,'-d',db_name], stdin=backup, check=True, timeout=60)
            with psycopg.connect(restored.set(drivername='postgresql').render_as_string(hide_password=False)) as db:
                original_revision = db.execute('SELECT version_num FROM alembic_version').fetchone()[0]
                if original_revision != before:
                    raise RuntimeError(f'Expected a pre-upgrade snapshot at {before}')
                projects = db.execute('SELECT count(*) FROM projects').fetchone()[0]
                files, assets = manifest(db, storage, before, complete)
            snapshot_store = directory / 'storage'
            snapshot_store.mkdir()
            copied = {}
            for key, digest in sorted(files.items()):
                path = safe_child(storage, key)
                destination = safe_child(snapshot_store, key)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                copied[key] = sha256(destination)
                if copied[key] != sha256(path) or (digest and copied[key] != digest):
                    raise RuntimeError('Referenced file hash differs: ' + key)
            (directory/'files.json').write_text(json.dumps(copied, indent=2)+'\n',encoding='utf-8')
            for arguments in (('upgrade',target),('check',),('downgrade',before),('upgrade',target),('check',)):
                run_alembic(restored,*arguments)
            with TemporaryDirectory(prefix='upgrade-recovery-',dir=directory) as folder:
                restored_store = Path(folder)
                shutil.copytree(snapshot_store, restored_store, dirs_exist_ok=True)
                for key, digest in copied.items():
                    if sha256(safe_child(restored_store,key)) != digest:
                        raise RuntimeError('Restored file hash differs: ' + key)
                api = verify_restored_api(restored,restored_store,projects,assets,target) if complete else None
            return {'before_revision':before,'tested_revision':target,'restored_separate_database':True,
                    'restored_separate_storage':True,'projects_verified':projects,'assets_verified':assets,
                    'files_verified':len(copied),'dump_sha256':sha256(dump),
                    'restored_api':api,'complete_production_storage':complete,
                    'migration_roundtrip':[f'upgrade {target}','schema check',f'downgrade {before}',f'upgrade {target}','schema check']}
        finally:
            connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(db_name)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upgrade', action='store_true', help='Upgrade the backed-up database after successful rehearsal')
    parser.add_argument('--stage', choices=['p6','p7','p10','p11','p12','p13','p14','director','director-batches'], default='p6')
    args = parser.parse_args()
    if args.upgrade:
        for port in (18000, 15173):
            with socket.socket() as listener:
                if listener.connect_ex(('127.0.0.1',port)) == 0:
                    raise SystemExit('Stop this project workbench before the on-disk upgrade')
    config = dotenv_values(ROOT / '.env')
    source = make_url(os.getenv('DATABASE_URL') or config['DATABASE_URL'])
    if source.host not in ('127.0.0.1','localhost','::1'):
        raise SystemExit('Only local PostgreSQL is permitted')
    storage = Path(os.getenv('STORAGE_ROOT') or config.get('STORAGE_ROOT') or 'data')
    storage = (ROOT / storage).resolve()
    live_url = source.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(live_url) as connection:
        pending = connection.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[0]
        if pending:
            raise SystemExit('Wait for active or queued tasks to finish before taking a snapshot')
    container = subprocess.check_output(['docker','compose','ps','-q','db'],cwd=ROOT,text=True).strip()
    if not container:
        raise SystemExit('Project PostgreSQL is not running')
    before, target = {
        'p6':('0006','0007'),'p7':('0007','0008'),'p10':('0008','0009'),'p11':('0009','0010'),
        'p12':('0010','0011'),'p13':('0011','0012'),'p14':('0012','0013'),
        'director':('0013','0014'),
        'director-batches':('0014','0015'),
    }[args.stage]
    directory = ROOT / 'data/backups' / (args.stage+'-before-' + uuid4().hex[:12])
    directory.mkdir(parents=True)
    report = snapshot_and_verify(source, storage, container, directory, before, target,
                                 complete=args.stage in ('p14','director','director-batches'))
    report['backup_directory'] = directory.relative_to(ROOT).as_posix()
    if args.upgrade:
        run_alembic(source,'upgrade',target)
        run_alembic(source,'check')
        report['local_database_revision']=target
    (ROOT/'data/tmp').mkdir(parents=True,exist_ok=True)
    report_path = ROOT/'data/tmp'/f'{args.stage}-backup-migration-acceptance.json'
    report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
