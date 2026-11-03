"""Block until PostgreSQL answers (and, with --migrations, until it is at the Alembic head).

Used as a Kubernetes initContainer so workers never start against an unmigrated schema.

    python -m scripts.wait_for_db [--migrations] [--timeout 300]
"""

import argparse
import asyncio
import sys
import time

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from database.session import create_engine


def _head() -> str:
    return ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()


async def _check(migrations: bool) -> str | None:
    """None when ready, otherwise a reason."""
    engine = create_engine(null_pool=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            if migrations:
                try:
                    current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                except Exception:
                    return "no alembic_version table yet"
                if current != _head():
                    return f"schema at {current}, waiting for {_head()}"
        return None
    except Exception as exc:
        return f"database not reachable ({type(exc).__name__})"
    finally:
        await engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--migrations", action="store_true")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()
    deadline = time.monotonic() + args.timeout
    while True:
        reason = asyncio.run(_check(args.migrations))
        if reason is None:
            print("ready", flush=True)
            return 0
        if time.monotonic() > deadline:
            print(f"timed out: {reason}", file=sys.stderr)
            return 1
        print(f"waiting: {reason}", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
