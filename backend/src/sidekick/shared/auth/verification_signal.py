"""A request-scoped signal that a bearer token was actually verified, not merely answered.

The ingress limit on failed bearer attempts (`sidekick.api.failed_auth`) must remember which tokens
are good without trusting a status code: a redirect or an open route answers 2xx or 3xx for any
token. So the code that really verifies a credential calls `mark_verified()` after it accepted it,
and the middleware reads the flag. The holder is a plain mutable object in a context variable, so
the mark survives a thread hop (`anyio.to_thread` copies the context but shares the object) and any
layer that copies the ASGI scope. Outside a watched request it does nothing.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar


class Verification:
    """Whether a credential was verified while this request was handled."""

    def __init__(self) -> None:
        self.verified = False


_CURRENT: ContextVar[Verification | None] = ContextVar("sidekick_verification", default=None)


@contextmanager
def watch() -> Generator[Verification]:
    """Observe `mark_verified()` calls made while the body of the `with` runs."""

    verification = Verification()
    token = _CURRENT.set(verification)
    try:
        yield verification
    finally:
        _CURRENT.reset(token)


def mark_verified() -> None:
    """Record that a credential for this request has just been accepted."""

    verification = _CURRENT.get()
    if verification is not None:
        verification.verified = True
