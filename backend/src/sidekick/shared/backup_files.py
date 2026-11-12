"""File-name convention of finished owner backups, shared by the backup writer and the health check.

The worker health check (`sidekick.shared.worker_health`) judges the last successful backup from
the names alone, so the convention sits in the shared kernel rather than in `sidekick.backup`.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

BACKUP_FILE_PREFIX = "sidekick-backup-"
BACKUP_FILE_SUFFIX = ".skbackup"

_FINISHED_BACKUP_NAME = re.compile(
    re.escape(BACKUP_FILE_PREFIX) + r"(\d{8}T\d{6}Z)-[0-9a-f]{12}" + re.escape(BACKUP_FILE_SUFFIX)
)


def finished_backup_time(name: str) -> datetime | None:
    """UTC time in a finished backup file name, or None for any other name.

    Only a name of exactly the finished form counts: a temporary, hidden or partial file (a
    leading dot, a `.tmp` ending, an extra suffix) never does. Retention and the monitoring of
    the last successful backup both read names through this one function.
    """

    match = _FINISHED_BACKUP_NAME.fullmatch(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def latest_backup_time(directory: Path) -> datetime | None:
    """UTC time of the newest finished backup file in `directory`, from its file name.

    A file stays on disk as finished only when it was written and read back successfully, so the
    newest one is the last successful backup. `None` if there is none.
    """

    newest: datetime | None = None
    try:
        files = [path for path in directory.iterdir() if path.is_file()]
    except OSError:
        return None
    for path in files:
        created = finished_backup_time(path.name)
        if created is not None and (newest is None or created > newest):
            newest = created
    return newest
