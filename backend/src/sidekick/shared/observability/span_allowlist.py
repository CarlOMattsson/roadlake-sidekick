"""Only reviewed span names, attribute keys and server-owned component names leave the process.

FastMCP names its spans after the *request* (`tools/call <name>`, `resources/read <uri>`) and sets
the name or URI the client sent as attributes (`fastmcp.component.key`, `gen_ai.tool.name`,
`mcp.resource.uri`), so a client that calls an unknown tool named after an e-mail address would put
that address in every exported span. Sidekick cannot change those call sites. This processor runs
first in the provider's chain (`harden_tracer_provider`) and rewrites each ended span:

* the name is kept when it is on the fixed list, or when it is `<method> <component>` and the
  component is one the server registered; any other component becomes `tool:unknown`,
  `resource:unknown` or `prompt:unknown`; any other name becomes `span:unknown`;
* an attribute is kept only when its key is on `SAFE_SPAN_ATTRIBUTES`; those that carry a
  component name or URI are validated against the registered names the same way;
* event names other than `exception`, event attributes and link attributes follow the same key list.
"""

import threading
from collections.abc import Iterable, Mapping
from typing import Any, Final

from opentelemetry.sdk.trace import Event, ReadableSpan, SpanProcessor
from opentelemetry.trace import Link

from .port import SAFE_ATTRIBUTE_NAMES

TOOL: Final = "tool"
RESOURCE: Final = "resource"
PROMPT: Final = "prompt"
_UNKNOWN: Final = "unknown"

# Attributes Sidekick's own spans carry (`SAFE_ATTRIBUTE_NAMES`, already filtered by the telemetry
# port) and the ones FastMCP sets itself. Left out on purpose: `enduser.id`, `enduser.scope` and
# `mcp.session.id` (identifiers), and every attribute an instrumentation might add later.
SAFE_SPAN_ATTRIBUTES: Final = SAFE_ATTRIBUTE_NAMES | frozenset(
    {
        "exception.type",
        "error.type",
        "mcp.method.name",
        "mcp.protocol.version",
        "fastmcp.server.name",
        "fastmcp.span.seam",
        "fastmcp.component.type",
        "fastmcp.component.key",
        "fastmcp.provider.type",
        "gen_ai.tool.name",
        "gen_ai.prompt.name",
        "mcp.resource.uri",
    }
)

# MCP/JSON-RPC protocol methods, as the SDK defines them. The one list that span names, the
# `mcp.method.name` attribute and the request log line share (`safe_mcp_method`).
MCP_METHODS: Final = frozenset(
    {
        "initialize",
        "ping",
        "server/discover",
        "subscriptions/listen",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/templates/list",
        "resources/read",
        "resources/subscribe",
        "resources/unsubscribe",
        "prompts/list",
        "prompts/get",
        "logging/setLevel",
        "completion/complete",
        "roots/list",
        "sampling/createMessage",
        "elicitation/create",
        "tasks/get",
        "tasks/list",
        "tasks/cancel",
        "tasks/result",
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/progress",
        "notifications/message",
        "notifications/prompts/list_changed",
        "notifications/resources/list_changed",
        "notifications/resources/updated",
        "notifications/roots/list_changed",
        "notifications/subscriptions/acknowledged",
        "notifications/tools/list_changed",
    }
)
_OTHER_METHOD: Final = "other"

# Span names the server itself produces: Sidekick's own operations, the HTTP request span and the
# MCP protocol methods.
SAFE_SPAN_NAMES: Final = (
    frozenset(
        {
            "mcp.tool",
            "search.operation",
            "db.transaction",
            "external_reference.operation",
            "shopping.operation",
            "http.request",
        }
    )
    | MCP_METHODS
)


def safe_mcp_method(name: str | None) -> str:
    """The protocol method when it is on the fixed list, else `other`."""

    return name if name is not None and name in MCP_METHODS else _OTHER_METHOD


_SPAN_NAME_METHODS: Final = {
    "tools/call": TOOL,
    "resources/read": RESOURCE,
    "prompts/get": PROMPT,
}
_COMPONENT_ATTRIBUTES: Final = {
    "gen_ai.tool.name": TOOL,
    "gen_ai.prompt.name": PROMPT,
    "mcp.resource.uri": RESOURCE,
}
_DELEGATE: Final = "delegate"

_lock = threading.Lock()
_registered: dict[str, frozenset[str]] = {
    TOOL: frozenset(),
    RESOURCE: frozenset(),
    PROMPT: frozenset(),
}


def register_trusted_mcp_names(
    *,
    tools: Iterable[str] = (),
    resources: Iterable[str] = (),
    prompts: Iterable[str] = (),
) -> None:
    """Add the tool names, resource URIs and prompt names the server owns. Additive."""

    with _lock:
        _registered[TOOL] = _registered[TOOL] | frozenset(tools)
        _registered[RESOURCE] = _registered[RESOURCE] | frozenset(resources)
        _registered[PROMPT] = _registered[PROMPT] | frozenset(prompts)


def is_registered_tool(name: str) -> bool:
    """Whether the server registered a tool of this name; the one registry spans and logs share."""

    return name in _registered[TOOL]


def _component(kind: str, name: str) -> str:
    """The name itself when the server registered it, else the generic `kind:unknown`."""

    return name if name in _registered[kind] else f"{kind}:{_UNKNOWN}"


def normalize_span_name(name: str) -> str:
    """The name a span may be exported under."""

    if name in SAFE_SPAN_NAMES:
        return name
    method, _, component = name.partition(" ")
    if method in _SPAN_NAME_METHODS and component:
        return f"{method} {_component(_SPAN_NAME_METHODS[method], component)}"
    if method == _DELEGATE and component:
        known = any(component in names for names in _registered.values())
        return f"{_DELEGATE} {component if known else _UNKNOWN}"
    return f"span:{_UNKNOWN}"


def _component_key(key: str) -> str:
    """A FastMCP component key reduced to a registered name, or `unknown`.

    Keys come as `tool:name@version` (the kind is a prefix) or as the bare name or URI.
    """

    if not key:
        return key
    kind, separator, rest = key.partition(":")
    if separator and kind in _registered:
        name = rest.rsplit("@", 1)[0]
        return f"{kind}:{name}" if name in _registered[kind] else f"{kind}:{_UNKNOWN}"
    bare = key.rsplit("@", 1)[0]
    return bare if any(bare in names for names in _registered.values()) else _UNKNOWN


def _safe_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for key, value in (attributes or {}).items():
        if key not in SAFE_SPAN_ATTRIBUTES:
            continue
        if key in _COMPONENT_ATTRIBUTES:
            value = _component(_COMPONENT_ATTRIBUTES[key], str(value))
        elif key == "fastmcp.component.key":
            value = _component_key(str(value))
        elif key == "mcp.method.name":
            value = value if value in SAFE_SPAN_NAMES else _UNKNOWN
        kept[key] = value
    return kept


class SpanAllowlistProcessor(SpanProcessor):
    """Rewrite each ended span so only allowlisted names and attributes remain."""

    def on_end(self, span: ReadableSpan) -> None:
        mutable: Any = span
        mutable._name = normalize_span_name(span.name)
        mutable._attributes = _safe_attributes(span.attributes)
        mutable._events = [
            Event(
                event.name if event.name == "exception" else "event",
                _safe_attributes(event.attributes),
                event.timestamp,
            )
            for event in span.events
        ]
        mutable._links = [
            Link(link.context, _safe_attributes(link.attributes)) for link in span.links
        ]
