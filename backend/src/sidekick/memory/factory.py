"""Builds the memory provider the settings select. Shared by the API container and the worker."""

from __future__ import annotations

from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.adapters.hindsight import HindsightMemoryProvider
from sidekick.memory.ports import MemoryProvider
from sidekick.shared.config import Settings


def build_provider(settings: Settings) -> MemoryProvider:
    """The provider the settings select. Configuration errors raise ValueError without secrets."""

    if settings.memory_provider == "fake":
        return FakeMemoryProvider()
    token = settings.memory_hindsight_api_token
    key = settings.memory_id_derivation_key
    if token is None or key is None:
        raise ValueError("memory provider configuration is incomplete")
    return HindsightMemoryProvider(
        base_url=settings.memory_hindsight_base_url,
        api_token=token.get_secret_value(),
        id_derivation_key=key.get_secret_value(),
        allow_loopback=settings.memory_allow_loopback,
        max_response_bytes=settings.memory_hindsight_max_response_bytes,
    )
