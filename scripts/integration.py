"""Run against an explicitly configured disposable PostgreSQL database."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
url = os.getenv('TEST_DATABASE_URL')
if not url:
    raise SystemExit('Set TEST_DATABASE_URL to a disposable PostgreSQL database first.')
env = {**os.environ, 'DATABASE_URL': url}
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=root / 'backend', env=env, check=True)
raise SystemExit(subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=root / 'backend', env=env).returncode)
