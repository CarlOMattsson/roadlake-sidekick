"""Startup check that the runtime database role cannot change the schema (production only).

The application role must be a plain data role: not a superuser, not a member of the role that
owns the application schema, without CREATE on that schema, owning no table, sequence, view or
function in it (directly or through a role it is a member of), and without BYPASSRLS, CREATEROLE or
CREATEDB. A role that is any of those can alter or drop tables, skip row-level security or mint new
roles and, through a defect, turn a bug into a schema change. The migration role is the only one
that may change the schema. The failure message names the rule that failed and never a role name,
a host, a URL or a password.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.errors.core import InternalFaultError

from .models import SCHEMA

_ROLE_FACTS = text(
    """
    SELECT r.rolsuper,
           pg_has_role(current_user, n.nspowner, 'MEMBER'),
           has_schema_privilege(current_user, n.oid, 'CREATE'),
           EXISTS (SELECT 1 FROM pg_class AS c
                   WHERE c.relnamespace = n.oid
                     AND pg_has_role(current_user, c.relowner, 'MEMBER'))
           OR EXISTS (SELECT 1 FROM pg_proc AS p
                      WHERE p.pronamespace = n.oid
                        AND pg_has_role(current_user, p.proowner, 'MEMBER')),
           r.rolbypassrls,
           r.rolcreaterole,
           r.rolcreatedb
    FROM pg_roles AS r CROSS JOIN pg_namespace AS n
    WHERE r.rolname = current_user AND n.nspname = :schema
    """
)


class UnsafeRuntimeRoleError(InternalFaultError):
    """The runtime database role may change the schema, or its privileges could not be verified."""


@dataclass(frozen=True)
class RuntimeRoleFacts:
    is_superuser: bool
    is_schema_owner: bool
    can_create_in_schema: bool
    owns_schema_objects: bool = False
    bypasses_row_level_security: bool = False
    can_create_roles: bool = False
    can_create_databases: bool = False


def runtime_role_violation(facts: RuntimeRoleFacts) -> str | None:
    """The reason the role is unsafe for the application, or None when it is a plain data role."""

    if facts.is_superuser:
        return "the database role is a superuser"
    if facts.is_schema_owner:
        return "the database role owns the application schema"
    if facts.can_create_in_schema:
        return "the database role can create objects in the application schema"
    if facts.owns_schema_objects:
        return "the database role owns objects in the application schema"
    if facts.bypasses_row_level_security:
        return "the database role bypasses row-level security"
    if facts.can_create_roles:
        return "the database role can create roles"
    if facts.can_create_databases:
        return "the database role can create databases"
    return None


def require_unprivileged_runtime_role(factory: sessionmaker[Session]) -> None:
    """Raise UnsafeRuntimeRoleError unless the role behind `factory` is a plain data role.

    Fails closed: a database that cannot be queried, or a schema that cannot be found, is also a
    refusal. The underlying driver error is not chained, so no connection detail reaches the log.
    """

    try:
        with factory() as session:
            row = session.execute(_ROLE_FACTS, {"schema": SCHEMA}).one_or_none()
    except Exception:
        raise UnsafeRuntimeRoleError(
            "cannot verify the database role: the database is unreachable or the schema is missing"
        ) from None
    if row is None:
        raise UnsafeRuntimeRoleError("cannot verify the database role: the schema is missing")
    violation = runtime_role_violation(
        RuntimeRoleFacts(
            is_superuser=bool(row[0]),
            is_schema_owner=bool(row[1]),
            can_create_in_schema=bool(row[2]),
            owns_schema_objects=bool(row[3]),
            bypasses_row_level_security=bool(row[4]),
            can_create_roles=bool(row[5]),
            can_create_databases=bool(row[6]),
        )
    )
    if violation is not None:
        raise UnsafeRuntimeRoleError(f"refusing to start in production: {violation}")
