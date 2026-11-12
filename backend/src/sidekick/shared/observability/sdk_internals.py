"""Check the OpenTelemetry SDK internals the span redaction rewrites.

The span allowlist and the exception scrubber change an ended span by assigning to the private
fields `_name`, `_attributes`, `_events`, `_links` and `_status` of `ReadableSpan` (the SDK offers
no public way to rewrite a span on its way to an exporter). If a release renamed one of them, the
assignment would create an unused attribute and the original content would be exported unchanged.
`span_rewrite_problem` proves at startup that each assignment changes what the span's public
accessors, which exporters read, return. The SDK is pinned to `REVIEWED_OTEL_SDK_VERSION` in
`pyproject.toml`; `tests/unit/test_library_internals_pins.py` fails when the pin and this
constant drift.
"""

from typing import Any, Final

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.trace import INVALID_SPAN_CONTEXT, Link, Status, StatusCode

#: The opentelemetry-sdk release whose `ReadableSpan` fields the redaction was reviewed against.
REVIEWED_OTEL_SDK_VERSION: Final = "1.45.2"

_EVENT: Final = Event("rewritten", {}, 0)
_LINK: Final = Link(INVALID_SPAN_CONTEXT)
_STATUS: Final = Status(StatusCode.OK)

#: Private field the redaction writes, the value written, the public accessor and what it returns.
_REWRITTEN_FIELDS: Final[tuple[tuple[str, Any, str, Any], ...]] = (
    ("_name", "rewritten", "name", "rewritten"),
    ("_attributes", {"rewritten": "yes"}, "attributes", {"rewritten": "yes"}),
    ("_events", [_EVENT], "events", (_EVENT,)),
    ("_links", [_LINK], "links", (_LINK,)),
    ("_status", _STATUS, "status", _STATUS),
)


def span_rewrite_problem() -> str | None:
    """Return the first private field the SDK no longer reads, or None when all are as reviewed."""

    span: Any = ReadableSpan("probe")
    for private, value, public, expected in _REWRITTEN_FIELDS:
        try:
            setattr(span, private, value)
            if getattr(span, public) != expected:
                return private
        except Exception:
            return private
    return None
