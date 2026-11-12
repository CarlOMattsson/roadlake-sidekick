"""Declarative base, schema name and the retained-table registry for every mapping module."""

from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, Mapper
from sqlalchemy.sql.expression import FromClause

from sidekick.shared.compat import set_mapper_sort_key

# The PostgreSQL schema that holds every table. The baseline migration creates it by the same name;
# tests/integration/test_migration_baseline.py fails if the two ever differ.
SCHEMA = "sidekick"


class Base(DeclarativeBase):
    pass


# Tables that stay in the database but have no ORM mapping, because nothing reads or writes them any
# more. Dropping a table is a separate contract migration; until then the rows stay as they are and
# the migrations keep owning the DDL. None at present: `sessions` (browser sign-in, D-082) is not
# in the 0.1.0 baseline. Name a table here, with the reason, instead of leaving a stale model.
RETAINED_UNMAPPED_TABLES: frozenset[str] = frozenset()


@event.listens_for(Mapper, "after_configured")
def order_flushes_by_foreign_keys() -> None:
    """Make one flush insert referenced rows before the rows that reference them.

    The unit of work orders mappers that have no `relationship()` between them by
    `<module>.<ClassName>`, not by foreign key, so a project and its task added together reached the
    database in the order of their module and class names. Prefixing each mapper's sort key with the
    position of its table in `metadata.sorted_tables` makes that tie-break follow the foreign keys
    declared in the metadata. It runs after every (re)configuration, so mappings imported later
    (shopping, references) are ordered too. `Mapper._sort_key` is private; SQLAlchemy is pinned to
    one version (`pyproject.toml`) and `tests/integration/test_flush_order.py` fails if it stops
    working.
    """
    rank: dict[FromClause, int] = {
        table: position for position, table in enumerate(Base.metadata.sorted_tables)
    }
    for mapper in Base.registry.mappers:
        name = f"{mapper.class_.__module__}.{mapper.class_.__name__}"
        set_mapper_sort_key(mapper, f"{rank[mapper.local_table]:04d}.{name}")
