"""Verify P5 DB backups in disposable local databases; never replace the project DB."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
config = dotenv_values(ROOT / '.env')
source = make_url(os.getenv('DATABASE_URL') or config['DATABASE_URL'])
if source.host not in ('127.0.0.1', 'localhost', '::1'):
    raise SystemExit('Only local PostgreSQL is permitted')
container = subprocess.check_output(['docker','compose','ps','-q','db'], cwd=ROOT, text=True).strip()
if not container:
    raise SystemExit('Project database container is not running')
admin = source.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False)
storage = Path(os.getenv('STORAGE_ROOT') or config.get('STORAGE_ROOT') or 'data')
storage = (ROOT / storage).resolve() if not storage.is_absolute() else storage.resolve()
before = ROOT / 'data/backups/p5-before/database.dump'
after = ROOT / 'data/backups' / ('p5-verified-' + uuid4().hex[:12]) / 'database.dump'
after.parent.mkdir(parents=True, exist_ok=False)
with after.open('wb') as output:
    subprocess.run(['docker','exec',container,'pg_dump','-U',source.username,'-d',source.database,'-Fc'],
                   stdout=output, check=True, timeout=60)
report = {'database_only_backup': True, 'original_files_copied': False, 'restores': []}
with psycopg.connect(admin, autocommit=True) as connection:
    for backup, expected in ((before,'0005'),(after,'0006')):
        db_name = 'story_p5_restore_' + uuid4().hex[:12]
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db_name)))
        try:
            with backup.open('rb') as input_file:
                subprocess.run(['docker','exec','-i',container,'pg_restore','--exit-on-error','--no-owner',
                                '-U',source.username,'-d',db_name], stdin=input_file,check=True,timeout=60)
            with psycopg.connect(source.set(drivername='postgresql',database=db_name).render_as_string(hide_password=False)) as restored:
                revision = restored.execute('SELECT version_num FROM alembic_version').fetchone()[0]
                assert revision == expected
                count = restored.execute('SELECT count(*) FROM projects').fetchone()[0]
                assets = restored.execute('SELECT storage_key,sha256 FROM assets').fetchall()
                for key,digest in assets:
                    path = (storage / key).resolve()
                    assert path.is_relative_to(storage), 'Unsafe asset key in backup'
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Original asset hash differs'
                financial = restored.execute('SELECT count(*) FROM model_ledger').fetchone()[0] if revision=='0006' else None
            report['restores'].append({'backup':str(backup.relative_to(ROOT)),'revision':revision,
                'projects':count,'original_asset_hashes_checked':len(assets),'ledger_rows':financial,
                'dump_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'restored_in_separate_database':True})
        finally:
            connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(db_name)))
    # Exercise a reversible migration using an empty disposable database only.
    db_name = 'story_p5_migration_' + uuid4().hex[:12]
    connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db_name)))
    try:
        env = {**os.environ,'DATABASE_URL':source.set(database=db_name).render_as_string(hide_password=False),
               'AI_STORY_ENABLE_PAID_TEXT':'0'}
        for arguments in (('upgrade','head'),('downgrade','0005'),('upgrade','head'),('check',)):
            subprocess.run([sys.executable,'-m','alembic',*arguments],cwd=ROOT/'backend',env=env,check=True,timeout=30)
        report['empty_database_migration'] = ['upgrade 0006','downgrade 0005','upgrade 0006','schema check passed']
    finally:
        connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(db_name)))
(ROOT/'docs/p5-backup-migration-acceptance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print('P5 separate DB restores, original hashes and empty migration round-trip passed.')
