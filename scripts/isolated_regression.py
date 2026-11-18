"""Create a disposable PostgreSQL database and run the current backend suite."""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from tempfile import TemporaryDirectory
import socket
import sysconfig

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]

def run_browser(env, path):
    for port in (15173, 18000):
        with socket.socket() as listener:
            if listener.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"QA requires a free loopback port: {port}")
    executable = sys.executable
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        # The Windows venv launcher spawns a child that can outlive terminate().
        executable = sys._base_executable
        env = {**env, "PYTHONPATH": sysconfig.get_path("purelib")}
    jobs = [
        ("api", [executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18000"], "backend"),
        ("worker", [executable, "-m", "app.worker"], "backend"),
        ("vite", ["node", "node_modules/vite/bin/vite.js", "--strictPort"], "frontend"),
    ]
    with ExitStack() as stack:
        for label, command, directory in jobs:
            log = stack.enter_context((path / f"{label}.log").open("wb"))
            process = subprocess.Popen(command, cwd=ROOT / directory, env=env, stdout=log, stderr=subprocess.STDOUT)
            stack.callback(process.wait, 15)
            stack.callback(process.terminate)
        subprocess.run(["node", "--experimental-websocket", "scripts/browser-p5.mjs"], cwd=ROOT,
                       env=env, check=True, timeout=110)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-only", action="store_true")
    args = parser.parse_args()
    source = make_url(os.getenv("DATABASE_URL") or dotenv_values(ROOT / ".env")["DATABASE_URL"])
    if source.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("This script only accepts a local PostgreSQL server.")
    db_name = f"story_v2_test_{uuid4().hex[:12]}"
    admin = source.set(drivername="postgresql", database="postgres")
    target = source.set(database=db_name)
    env = {
        **os.environ,
        "DATABASE_URL": target.render_as_string(hide_password=False),
        "TEST_DATABASE_URL": target.render_as_string(hide_password=False),
        "AI_STORY_ENABLE_PAID_TEXT": "0",
    }

    def run(module, *arguments):
        subprocess.run(
            [sys.executable, "-m", module, *arguments],
            cwd=ROOT / "backend", env=env, check=True,
        )

    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        try:
            run("alembic", "upgrade", "head")
            run("alembic", "check")
            options = ("--junitxml", str(args.junitxml.resolve())) if args.junitxml else ()
            if not args.browser_only:
                run("pytest", "-q", *options)
            if args.browser or args.browser_only:
                (ROOT / "data" / "tmp").mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(prefix="browser-qa-", dir=ROOT / "data" / "tmp", ignore_cleanup_errors=True) as folder:
                    run_browser({**env, "STORAGE_ROOT": folder, "AI_STORY_QA_ROOT": folder}, Path(folder))
        finally:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))


if __name__ == "__main__":
    main()
