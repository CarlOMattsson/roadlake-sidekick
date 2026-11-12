"""The base of every closed record: unknown fields are refused."""

from pydantic import BaseModel, ConfigDict


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
