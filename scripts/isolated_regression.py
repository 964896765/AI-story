"""Create a disposable PostgreSQL database and run the current backend suite."""
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", type=Path)
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
            run("pytest", "-q", *options)
        finally:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))


if __name__ == "__main__":
    main()
