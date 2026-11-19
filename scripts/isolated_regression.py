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
BROWSER_PHASES = ('p5', 'p6', 'p6-ocr', *(f'p{number}' for number in range(7,15)))

def run_browser(env, path, phases):
    api_port, browser_port = 18006, 15179
    for port in (api_port, browser_port):
        with socket.socket() as listener:
            if listener.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"QA requires a free loopback port: {port}")
    executable = sys.executable
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        # The Windows venv launcher spawns a child that can outlive terminate().
        executable = sys._base_executable
        env = {**env, "PYTHONPATH": sysconfig.get_path("purelib")}
    env = {**env, "AI_STORY_QA_API_PORT":str(api_port), "AI_STORY_QA_WEB_PORT":str(browser_port),
           "FRONTEND_ORIGIN":f"http://127.0.0.1:{browser_port}"}
    jobs = [
        ("api", [executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)], "backend"),
        ("worker", [executable, "-m", "app.worker"], "backend"),
        ("vite", ["node", "node_modules/vite/bin/vite.js", *(["preview"] if {'p14','p6-ocr','p10'}.intersection(phases) else []),
                  "--host", "127.0.0.1", "--strictPort", "--port", str(browser_port)], "frontend"),
    ]
    with ExitStack() as stack:
        for label, command, directory in jobs:
            log = stack.enter_context((path / f"{label}.log").open("wb"))
            process = subprocess.Popen(command, cwd=ROOT / directory, env=env, stdout=log, stderr=subprocess.STDOUT)
            stack.callback(process.wait, 15)
            stack.callback(process.terminate)
        for phase in phases:
            subprocess.run(["node", "--experimental-websocket", f"scripts/browser-{phase}.mjs"], cwd=ROOT,
                           env=env, check=True, timeout=110)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-only", action="store_true")
    parser.add_argument("--browser-phase", choices=BROWSER_PHASES, default="p5")
    parser.add_argument("--all-browsers", action="store_true", help="Run P5–P14 flows against the built frontend")
    parser.add_argument("--browser-evidence", type=Path, default=ROOT / "data" / "tmp")
    parser.add_argument("--test-file", help="Optional pytest path or node ID relative to backend")
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
                run("pytest", "-q", *options, *([args.test_file] if args.test_file else []))
            if args.browser or args.browser_only or args.all_browsers:
                (ROOT / "data" / "tmp").mkdir(parents=True, exist_ok=True)
                evidence = args.browser_evidence.resolve()
                evidence.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(prefix="browser-qa-", dir=ROOT / "data" / "tmp", ignore_cleanup_errors=True) as folder:
                    run_browser({**env, "STORAGE_ROOT": folder, "AI_STORY_QA_ROOT": folder,
                                 "AI_STORY_QA_EVIDENCE": str(evidence)}, Path(folder),
                                BROWSER_PHASES if args.all_browsers else (args.browser_phase,))
        finally:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))


if __name__ == "__main__":
    main()
