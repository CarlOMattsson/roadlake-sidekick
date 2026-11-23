"""Readiness of an api process: the database answers and the schema is at the image's revision.

Used by `/health/ready` and, as `python -m sidekick.shared.readiness`, by the self-hosted compose
healthcheck and the updater. The public surface answers 404 for `/health/*` in `github_oauth`
mode, so the container checks itself with this command instead of over HTTP.

The expected migrations are every numbered file in the image's `migrations/` directory. The check
passes when all of them are among the applied migrations: a database that is ahead of the image
(an expand-class rollback to the previous image) is still ready, a database that is behind is not.
The newest number alone proves nothing, because the chain does not follow the numbers (124 comes
before 121), so a database that has 124 but not 121 is behind.
The answer carries no data: exit status 0 or 1 and one word on stdout.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

# backend/src/sidekick/shared/readiness.py -> the directory that holds `migrations/`
# (the repository root in a checkout, /app in the image).
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"


def expected_migration_ids(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[str]:
    """The ids of every numbered migration file, in number order."""

    numbered: list[tuple[int, str]] = []
    for path in migrations_dir.glob("*.py"):
        number, separator, _ = path.stem.partition("_")
        if separator and number.isdigit():
            numbered.append((int(number), path.stem))
    if not numbered:
        raise FileNotFoundError("no numbered migrations found")
    return [name for _, name in sorted(numbered)]


def schema_is_ready(session: Session, expected_ids: Sequence[str]) -> bool:
    """True when the database answers and every id of `expected_ids` is among the applied ones."""

    applied = set(session.scalars(text("SELECT migration_id FROM public._yoyo_migration")))
    return applied.issuperset(expected_ids)


def is_ready(
    session_factory: sessionmaker[Session], migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
) -> bool:
    """Never raises: any failure (no database, no grant, no migrations directory) is not ready."""

    try:
        expected = expected_migration_ids(migrations_dir)
        with session_factory() as session:
            return schema_is_ready(session, expected)
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
