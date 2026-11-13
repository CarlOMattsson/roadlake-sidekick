"""An export stamped with a head of the folded development chain restores into the current schema.

The baseline folded `100_baseline_0_1_0`..`105_drop_sessions_and_password_hash`; an export or backup
from the owner's installation carries one of those ids. The export never holds `sessions`,
`users.password_hash` or the audit log (they are in `EXCLUDED_COLLECTIONS`), so the stamp is only a
label: a document of any folded head is a format 4 export, which differs from the current format
only by four empty collections of the retired automation engine. Restoring it works on the current
schema, and the audit row it writes takes the new `audit_events.source` column's
default (NULL: a restore runs outside a request).
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.owner_export.catalogue import EXCLUDED_COLLECTIONS
from sidekick.owner_export.document import verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.types import Actor
from sidekick.store import SqlAlchemyStore
from tests.db import database_factory
from tests.support.older_export_formats import BASELINE_HEAD, as_format_4
from tests.support.settings import make_settings


def _audit_rows(factory: sessionmaker[Session], owner: UUID) -> list[Any]:
    with factory() as session:
        return list(
            session.execute(
                text(
                    "SELECT source FROM sidekick.audit_events "
                    "WHERE event = 'owner.restore' AND target_id = :owner"
                ),
                {"owner": owner},
            ).all()
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "head",
    ["102_event_ledger_append_only", "105_drop_sessions_and_password_hash", BASELINE_HEAD],
)
def test_an_export_stamped_with_a_folded_head_restores_on_the_current_schema(head: str) -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    source = container.auth.provision_user(f"fold-source-{head[:3]}", "Source")
    target = container.auth.provision_user(f"fold-target-{head[:3]}", "Target")
    exported = OwnerExportService(SqlAlchemyStore(factory)).export(Actor(source, frozenset()))
    document = as_format_4(exported, head)

    assert verify_export(document).owner_id == source
    # Nothing of the removed sign-in or of the audit log is part of the document.
    assert {"sessions_and_csrf_digests", "users_and_password_hashes"} <= set(EXCLUDED_COLLECTIONS)
    assert not {"sessions", "users", "audit_events"} & set(document["collections"])
    plan = build_restore_plan(document, target)
    assert plan.status == "ready"

    OwnerRestoreService(SqlAlchemyStore(factory)).restore(
        document, target_owner_id=target, expected_plan_checksum=plan.plan_checksum
    )

    # The current schema has no `sessions` table or `password_hash`, and the audit row of the
    # restore takes the default of the new `source` column.
    with factory() as session:
        assert session.scalar(text("SELECT to_regclass('sidekick.sessions')")) is None
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "table_schema = 'sidekick' AND column_name = 'password_hash'"
                )
            )
            == 0
        )
    assert _audit_rows(factory, target) == [(None,)]
