"""HTTP boundary models; generated OpenAPI is the frontend contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Health(StrictModel):
    status: str
