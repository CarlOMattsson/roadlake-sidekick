# ADR-010: Every domain error derives from SidekickError

- Status: Accepted (2026-11-12); records the delivered design
- Date: 2026-11-12
- Owners: Sidekick application maintainers

## Context

The API, MCP and companion boundaries translate errors by class and `code`. Contexts had invented roots of their own
(`ValueError`, `LookupError`, `PermissionError`, bare `Exception`), so each boundary translated them ad hoc or let them
become an unexplained 500.

## Decision

All exception classes in `backend/src/sidekick` derive from `SidekickError` (`shared/errors/core.py`), which carries a
closed `code`. Bases and their codes: `ValidationError` (`validation_error`), `NotFoundError` (`not_found`),
`ConflictError` (`conflict`), `PermissionDeniedError` (`forbidden`), `RateLimitedError` (`rate_limited`) and
`InternalFaultError` (`internal_error`: a defect or an unavailable dependency, never a client error).

Mapping, unchanged by this ADR:

- REST: `not_found` 404, `conflict` 409, `validation_error` 422, `forbidden` 403, any other code 400.
  `internal_error` is re-raised and answered by the unexpected-error middleware as a 500 with a correlation id.
- Companion `_translate`: the same classes to the companion envelope; `InternalFaultError` returns nothing, so it is
  a server error.
- MCP: the error `code` selects a fixed message; an unknown code becomes `internal_error`. Exception text is never sent.

`backend/tests/policy/test_error_taxonomy_policy.py` fails when a class outside the tree is added. Its allowlist has
two entries: `InvalidInputError`, which stays a `ValueError` because the boundaries name it in `CLIENT_INPUT_ERRORS`
and callers that translate `ValueError` rely on it; and `CompanionProblem`, the companion response envelope itself,
raised and rendered only inside the companion route.

## Consequences

- A tree error that escapes to a generic REST route is answered as a 4xx (400 for an unmapped code), not a 500,
  except `InternalFaultError`, which stays a 500.
- Code that caught `ValueError` for `ExportRefused`, `ExportFormatError`, `EndpointRejected` or `KeyRejected` must catch
  the new class. `KeyRejected.reason` is now `.rejection`.

## Evidence

- `backend/src/sidekick/shared/errors/core.py`
- `backend/src/sidekick/api/app.py`, `backend/src/sidekick/api/companion.py` (`_translate`)
- `backend/src/sidekick/mcp/results.py`
- `backend/tests/policy/test_error_taxonomy_policy.py`
