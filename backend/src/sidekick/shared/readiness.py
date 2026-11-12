"""Readiness of an api process: the database answers and the schema is at the image's revision.

Used by `/health/ready` and, as `python -m sidekick.shared.readiness`, by the self-hosted compose
healthcheck and the updater. The public surface answers 404 for `/health/*` in `github_oauth`
mode, so the container checks itself with this command instead of over HTTP.

The expected revision is the newest numbered file in the image's `migrations/` directory. The
check passes when that id is among the applied migrations: a database that is ahead of the image
(an expand-class rollback to the previous image) is still ready, a database that is behind is not.
The answer carries no data: exit status 0 or 1 and one word on stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

# backend/src/sidekick/shared/readiness.py -> the directory that holds `migrations/`
# (the repository root in a checkout, /app in the image).
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"


def expected_schema_head(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> str:
    """The id of the newest numbered migration file, e.g. `101_tasks_project_and_due_indexes`."""

    numbered: list[tuple[int, str]] = []
    for path in migrations_dir.glob("*.py"):
        number, separator, _ = path.stem.partition("_")
        if separator and number.isdigit():
            numbered.append((int(number), path.stem))
    if not numbered:
        raise FileNotFoundError("no numbered migrations found")
    return max(numbered)[1]


def schema_is_ready(session: Session, expected_head: str) -> bool:
    """True when the database answers and `expected_head` is among the applied migrations."""

    return bool(
        session.scalar(
            text("SELECT EXISTS (SELECT 1 FROM public._yoyo_migration WHERE migration_id = :head)"),
            {"head": expected_head},
        )
    )


def is_ready(
    session_factory: sessionmaker[Session], migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
) -> bool:
    """Never raises: any failure (no database, no grant, no migrations directory) is not ready."""

    try:
        head = expected_schema_head(migrations_dir)
        with session_factory() as session:
            return schema_is_ready(session, head)
    except Exception:
        return False


def main() -> None:
    from sidekick.shared.config import get_settings
    from sidekick.shared.persistence import create_session_factory

    try:
        settings = get_settings()
        ready = is_ready(
            create_session_factory(settings.database_url, timeouts=settings.database_timeouts)
        )
    except Exception:
        ready = False
    sys.stdout.write("ok\n" if ready else "not ready\n")
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
