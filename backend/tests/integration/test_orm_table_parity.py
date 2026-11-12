"""Every table in the `sidekick` schema is mapped by the ORM or listed as retained and unmapped.

A table that nothing reads any more keeps its rows until the owner decides to drop it (D-084), but
it must be named in `RETAINED_UNMAPPED_TABLES` instead of lingering as a model nobody uses. A new
table without a model, or a model whose table is gone, fails here.
"""

import pytest
from sqlalchemy import create_engine, text

from sidekick.references.persistence import ExternalReferenceRow, TaskExternalReferenceRow
from sidekick.shared.persistence.models import RETAINED_UNMAPPED_TABLES, Base
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow, ShoppingStatusRow
from tests.db import database_factory, require_test_database_url

# Mappings outside the core package, imported so their tables are part of `Base.metadata`.
LATER_MAPPINGS = (
    ExternalReferenceRow,
    TaskExternalReferenceRow,
    ShoppingItemRow,
    ShoppingListRow,
    ShoppingStatusRow,
)

# Tables owned by the migration tool, not by Sidekick.
TOOLING_TABLES = {"_yoyo_migration", "_yoyo_log", "_yoyo_version", "yoyo_lock", "_yoyo_lock"}


@pytest.mark.integration
def test_every_table_is_mapped_or_explicitly_retained_unmapped() -> None:
    database_factory()
    engine = create_engine(require_test_database_url())
    try:
        with engine.connect() as connection:
            database_tables = set(
                connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'sidekick' AND table_type = 'BASE TABLE'"
                    )
                )
            )
    finally:
        engine.dispose()
    database_tables -= TOOLING_TABLES
    mapped = {table.name for table in Base.metadata.tables.values() if table.schema == "sidekick"}

    assert mapped.isdisjoint(RETAINED_UNMAPPED_TABLES)
    assert database_tables == mapped | RETAINED_UNMAPPED_TABLES


@pytest.mark.integration
def test_every_foreign_key_in_the_database_is_declared_in_the_orm_metadata() -> None:
    """The unit of work orders inserts by the metadata's foreign keys (`models/base.py`), so a key
    that exists only in a migration would let a flush write a child before its parent."""
    database_factory()
    engine = create_engine(require_test_database_url())
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text, c.confrelid::regclass::text,
                           (SELECT array_agg(a.attname ORDER BY k.ord)
                              FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                              JOIN pg_attribute a ON a.attrelid = c.conrelid
                               AND a.attnum = k.attnum),
                           (SELECT array_agg(a.attname ORDER BY k.ord)
                              FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                              JOIN pg_attribute a ON a.attrelid = c.confrelid
                               AND a.attnum = k.attnum)
                    FROM pg_constraint c
                    JOIN pg_namespace n ON n.oid = c.connamespace
                    WHERE c.contype = 'f' AND n.nspname = 'sidekick'
                    """
                )
            ).all()
    finally:
        engine.dispose()
    in_database = {
        (
            child.removeprefix("sidekick."),
            parent.removeprefix("sidekick."),
            tuple(cols),
            tuple(refs),
        )
        for child, parent, cols, refs in rows
    }
    in_metadata = {
        (
            table.name,
            key.referred_table.name,
            tuple(key.column_keys),
            tuple(element.column.name for element in key.elements),
        )
        for table in Base.metadata.tables.values()
        for key in table.foreign_key_constraints
    }

    assert all(mapping.__table__ in Base.metadata.tables.values() for mapping in LATER_MAPPINGS)
    assert in_database - in_metadata == set()
