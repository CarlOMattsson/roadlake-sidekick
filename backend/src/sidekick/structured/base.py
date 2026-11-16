"""The bases of every closed record: unknown fields are refused."""

from collections.abc import Mapping
from typing import Any, ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _advertise_no_defaults(schema: dict[str, Any]) -> None:
    """Leave `default` out of every property, so "omitted" and "explicit null" differ on the wire.

    A client that fills in the schema's defaults before sending would otherwise send every field
    as an explicit null, and a null clears a field that allows it.
    """

    for property_schema in schema.get("properties", {}).values():
        property_schema.pop("default", None)


class PartialChanges(Output):
    """The fields of a partial update: omitted stays, null clears where the field allows it.

    `model_fields_set` records what the caller sent. A field named in `fixed_fields` has no empty
    value to clear to, so an explicit null on it reads as "not sent". The published schema carries
    no defaults (see `_advertise_no_defaults`).
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_advertise_no_defaults)

    fixed_fields: ClassVar[frozenset[str]] = frozenset()
    requires_change: ClassVar[bool] = True

    @model_validator(mode="before")
    @classmethod
    def _ignore_null_on_fixed_fields(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        sent = cast("Mapping[object, object]", data)
        return {
            name: value
            for name, value in sent.items()
            if value is not None or name not in cls.fixed_fields
        }

    @model_validator(mode="after")
    def _require_a_change(self) -> Self:
        if self.requires_change and not self.model_fields_set:
            raise PydanticCustomError("no_change", "at least one change is required")
        return self
