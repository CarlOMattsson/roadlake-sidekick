"""The bases of every closed record: unknown fields are refused."""

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from sidekick.shared.errors import FieldValidationError


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WithIgnoredNulls(BaseModel):
    """The reply of an update: the nulls that were read as "not sent", for the caller to check."""

    ignored_nulls: list[str] = Field(
        default_factory=list,
        description="Fields sent as null and ignored; to empty a field, name it in clear.",
    )


def _advertise_no_defaults(schema: dict[str, Any]) -> None:
    """Leave `default` out of every property, so "omitted" and "explicit null" differ on the wire.

    A client that fills in the schema's defaults before sending would otherwise send every field
    as an explicit null.
    """

    for property_schema in schema.get("properties", {}).values():
        property_schema.pop("default", None)


# The `clear` parameter of an update tool: `Annotated[list[<Record>Clear], CLEAR_FIELDS] | None`.
CLEAR_FIELDS = Field(
    description="Fields to empty, by name; not also in changes.",
    json_schema_extra={"uniqueItems": True},
)

# Tags are replaced as a set: an empty list is how they are emptied, so they are never cleared.
_REPLACED_AS_A_SET = frozenset({"tags"})


class PartialChanges(Output):
    """The fields of a partial update: omitted stays, null is "not sent", `clear` empties.

    `model_fields_set` records what the caller sent. A null is read as "not sent", because some
    clients fill in null for every optional property; the names are kept in `ignored_nulls` so the
    reply can say so. A field is emptied only by naming it in the tool's `clear` list (see
    `resolve`). A field named in `fixed_fields` has no empty value, so it cannot be cleared. The
    published schema carries no defaults (see `_advertise_no_defaults`).
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_advertise_no_defaults)

    fixed_fields: ClassVar[frozenset[str]] = frozenset()
    requires_change: ClassVar[bool] = True

    _ignored_nulls: tuple[str, ...] = PrivateAttr(default=())

    @classmethod
    def clearable_fields(cls) -> tuple[str, ...]:
        """The fields a `clear` list may name, in declaration order."""

        return tuple(
            name
            for name in cls.model_fields
            if name not in cls.fixed_fields and name not in _REPLACED_AS_A_SET
        )

    @property
    def ignored_nulls(self) -> list[str]:
        """The fields sent as null and not named for clearing, in declaration order."""

        return list(self._ignored_nulls)

    @model_validator(mode="after")
    def _read_null_as_not_sent(self) -> Self:
        nulls = {name for name in self.model_fields_set if getattr(self, name) is None}
        self.model_fields_set.difference_update(nulls)
        self._ignored_nulls = tuple(name for name in type(self).model_fields if name in nulls)
        return self

    @classmethod
    def from_sent(cls, sent: Mapping[str, object]) -> Self:
        """The changes of a caller that sends null to clear (the companion API).

        A null on a clearable field clears it, as `clear` would; a null on any other field is
        read as not sent.
        """

        values = {name: value for name, value in sent.items() if value is not None}
        clearable = cls.clearable_fields()
        changes = cls.model_validate(values)
        changes.resolve(name for name, value in sent.items() if value is None and name in clearable)
        return changes

    def resolve(self, clear: Iterable[str] = ()) -> None:
        """Empty the `clear` fields, in place; refused when a field is both given and cleared.

        Afterwards a cleared field counts as sent with no value, which is what the use case
        applies. Also refused when nothing at all was sent and the update needs a change.
        """

        names = set(clear)
        rows = [f"changes.{name}: also named in clear" for name in self.model_fields_set & names]
        if not (self.model_fields_set or names) and self.requires_change:
            rows.append("changes: at least one change is required")
        if rows:
            raise FieldValidationError(rows)
        self.model_fields_set.update(names)
        self._ignored_nulls = tuple(name for name in self._ignored_nulls if name not in names)
