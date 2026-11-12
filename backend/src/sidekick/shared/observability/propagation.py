"""Trace-context propagation that reads and writes `traceparent` only.

W3C `tracestate` is free-form vendor text (`vendor=anna.svensson@example.com` is valid), and it
survives into the span context and the parent of every exported span. `baggage` is client text
too. Sidekick's allowlist is closed: the propagator accepts the `traceparent` header (a fixed
format of hex ids and flags, validated by the SDK) and nothing else. It is the global propagator
(`configure_observability`), so the HTTP middleware, the MCP SDK and FastMCP, which all extract
through `opentelemetry.propagate`, share it.
"""

from typing import Any

from opentelemetry.context import Context
from opentelemetry.propagators.textmap import (
    Getter,
    Setter,
    default_getter,
    default_setter,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_TRACEPARENT = "traceparent"


class _TraceparentOnlyGetter(Getter[Any]):
    def __init__(self, inner: Getter[Any]) -> None:
        self._inner = inner

    def get(self, carrier: Any, key: str) -> list[str] | None:
        return self._inner.get(carrier, key) if key.lower() == _TRACEPARENT else None

    def keys(self, carrier: Any) -> list[str]:
        return [key for key in self._inner.keys(carrier) if key.lower() == _TRACEPARENT]


class _TraceparentOnlySetter(Setter[Any]):
    def __init__(self, inner: Setter[Any]) -> None:
        self._inner = inner

    def set(self, carrier: Any, key: str, value: str) -> None:
        if key.lower() == _TRACEPARENT:
            self._inner.set(carrier, key, value)


class TraceparentOnlyPropagator(TraceContextTextMapPropagator):
    """`TraceContextTextMapPropagator` that never sees, keeps or sends `tracestate`."""

    def extract(
        self,
        carrier: Any,
        context: Context | None = None,
        getter: Getter[Any] = default_getter,
    ) -> Context:
        return super().extract(carrier, context, _TraceparentOnlyGetter(getter))

    def inject(
        self,
        carrier: Any,
        context: Context | None = None,
        setter: Setter[Any] = default_setter,
    ) -> None:
        super().inject(carrier, context, _TraceparentOnlySetter(setter))

    @property
    def fields(self) -> set[str]:
        return {_TRACEPARENT}


TRACEPARENT_ONLY = TraceparentOnlyPropagator()
