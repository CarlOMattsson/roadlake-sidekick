"""Transport-neutral errors safe to translate at adapter boundaries."""

from typing import Literal

from pydantic import ValidationError as ModelValidationError

# Closed, client-actionable reasons. Only reasons that the domain actually raises belong here.
SidekickErrorReason = Literal[
    "stale_version", "not_before_after_due", "not_completed", "nul_character"
]


class SidekickError(Exception):
    code = "sidekick_error"
    reason: SidekickErrorReason | None
    # The owner's name for the record involved. Only the MCP error text uses it; never log it.
    subject: str | None
    # What a stale-version conflict was about ("task", "shopping_item"); the MCP layer words it.
    subject_kind: str | None

    def __init__(
        self,
        *args: object,
        reason: SidekickErrorReason | None = None,
        subject: str | None = None,
        subject_kind: str | None = None,
    ) -> None:
        super().__init__(*args)
        self.reason = reason
        self.subject = subject
        self.subject_kind = subject_kind


class ValidationError(SidekickError):
    code = "validation_error"


class InvalidInputError(ValueError):
    """A client-supplied argument was rejected, for example a page size or a pagination cursor.

    The one `ValueError` the API and MCP boundaries answer as a client error (REST `400
    bad_request`, MCP `validation_error`). Any other `ValueError` is a defect and surfaces as an
    internal error with a correlation id. The text is never sent to the client. Stays a
    `ValueError` so callers that translate it, such as the journal and search services, still do.
    """


class RefusedError(ValidationError, ValueError):
    """A refusal whose text is fixed and holds no value, so an operator command may print it.

    Raise it only with a literal sentence ("active user not found"), never with a message built
    from a login, a label, an id or any other input. It stays a `ValueError` for the callers that
    already catch the refusals it replaced.
    """


# What the boundaries treat as a rejected client value: the explicit type above, and the error
# pydantic raises (itself a `ValueError`) when a command model rejects the input it was built from.
CLIENT_INPUT_ERRORS = (InvalidInputError, ModelValidationError)


class NotFoundError(SidekickError):
    code = "not_found"


class ConflictError(SidekickError):
    code = "conflict"


class PermissionDeniedError(SidekickError):
    """The caller lacks a right the operation needs (answered as 403 `forbidden`)."""

    code = "forbidden"


class AuthenticationRequiredError(SidekickError):
    """The call carries no verified identity (answered as MCP `unauthorized`)."""

    code = "unauthorized"


class RateLimitedError(SidekickError):
    """A per-owner or per-device limit was reached; the caller may retry later."""

    code = "rate_limited"


class InternalFaultError(SidekickError):
    """A defect or an unavailable dependency, never a client error.

    The API answers it as a 500 `internal_error` with a correlation id and the MCP boundary as
    `internal_error`; the text is never sent.
    """

    code = "internal_error"


class IdempotencyKeyReusedError(ConflictError):
    """An idempotency key was replayed with a different payload.

    Still a plain `conflict` for REST and MCP (same code, same text, no `reason`); the subtype
    only lets an adapter tell this case apart without comparing message strings.
    """

    def __init__(self) -> None:
        super().__init__("idempotency key was already used with another payload")
