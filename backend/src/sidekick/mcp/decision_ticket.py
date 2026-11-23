"""Signed, short-lived tickets that prove a decision the owner made came from the app (issue #53).

A decision only the owner makes (approving a plan, running it, approving an automation, approving a
group of suggestions) is refused unless the app made the call. The request `_meta` origin mark is
not enough in every host: Claude Desktop over stdio drops `params._meta` on the app's `tools/call`.
So the server also hands the app a *ticket* with the data the app renders the decision from, in the
result's `_meta` only (never in `content` or `structuredContent`, which a model may read). The app
sends it back as the `decision_ticket` argument of the decision tool.

A ticket is an HMAC over the action, the object id, the object's digest as the owner was shown it,
the owner, the client, an expiry and a random nonce. Verifying it is stateless except for the nonce,
which is spent once. In short: one key per purpose, derived from the server secret with a label, and
a ticket MACs the action, object, digest, owner, client, expiry and nonce, so none of them can be
swapped for another.

The nonce set lives in memory. A ticket lives 15 minutes and every decision also carries an
idempotency key, so a restart that forgets the set only opens a replay of a decision the owner
already made, once, inside that window. A table would add a migration and a lookup per decision for
no gain at that size; the set is pruned by expiry so it never grows past the tickets of 15 minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Final, cast

from fastmcp.server.dependencies import get_access_token
from pydantic import Field

if TYPE_CHECKING:
    from fastmcp.tools import ToolResult

    from sidekick.shared.types import Actor

DECISION_TICKETS_META: Final = "com.roadlake.sidekick/decisionTickets"
"""The result `_meta` key that carries the tickets: `{"<action>:<object id>": "<ticket>"}`."""

DECISION_TICKET_BINDING_META: Final = "com.roadlake.sidekick/decisionTicketBinding"
"""The tool meta that names the two arguments a ticket is bound to (`object` and `digest`).

A tool that carries it accepts a ticket in `decision_ticket` as proof of the app instead of the
request's origin mark. A tool without it (the photo tools, which no app card calls) still needs the
origin mark.
"""

TICKET_ARGUMENT: Final = "decision_ticket"
TICKET_LIFETIME_SECONDS: Final = 15 * 60
# A ticket is "v1.<expiry>.<nonce>.<mac>"; the version is part of what the MAC covers.
_VERSION: Final = "v1"
_KEY_LABEL: Final = b"sidekick/owner-decision-ticket/v1"
_MAX_TICKET_CHARS: Final = 160
_STDIO_CLIENT: Final = "stdio"

DecisionTicket = Annotated[
    str | None,
    Field(
        max_length=_MAX_TICKET_CHARS,
        description=(
            "App only. The proof the app got with the data it shows; never write one yourself."
        ),
    ),
]


class TicketRefusal(StrEnum):
    """Why a ticket did not prove the decision; the value is the suffix of the logged code."""

    MALFORMED = "malformed"
    MISMATCH = "mismatch"
    EXPIRED = "expired"
    USED = "used"


@dataclass(frozen=True, slots=True)
class SpentTicket:
    """A ticket that was accepted; its nonce is spent until `release` gives it back."""

    nonce: str


@dataclass(frozen=True, slots=True)
class TicketEntry:
    """What a ticket vouches for: the action, the object it applies to and its digest."""

    action: str
    object_id: str
    digest: str


def ticket_key(entry: TicketEntry) -> str:
    """The `_meta` map key for an entry, which the app builds the same way from the call."""

    return f"{entry.action}:{entry.object_id}"


def binding_of(tool_meta: Mapping[str, object] | None) -> tuple[str, str] | None:
    """The argument names (object id, digest) a tool's tickets are bound to, if it takes tickets."""

    declared = (tool_meta or {}).get(DECISION_TICKET_BINDING_META)
    if not isinstance(declared, dict):
        return None
    names = cast("dict[str, object]", declared)
    object_arg, digest_arg = names.get("object"), names.get("digest")
    if isinstance(object_arg, str) and isinstance(digest_arg, str):
        return object_arg, digest_arg
    return None


def ticket_binding(object_arg: str, digest_arg: str) -> dict[str, dict[str, str]]:
    """The tool meta that makes a tool take tickets bound to those two of its arguments."""

    return {DECISION_TICKET_BINDING_META: {"object": object_arg, "digest": digest_arg}}


def request_client_id() -> str:
    """The OAuth client of the request, or `stdio` when the request has no access token."""

    token = get_access_token()
    return token.client_id if token is not None and token.client_id else _STDIO_CLIENT


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class DecisionTickets:
    """Signs and verifies decision tickets with a key derived from a server secret."""

    def __init__(self, secret: str, *, clock: Callable[[], float] = time.time) -> None:
        # A single HMAC block keyed with the secret and a purpose label: the key of one purpose
        # reveals nothing about the secret or about the keys of other purposes (cursors, tokens).
        self._key = hmac.new(secret.encode(), _KEY_LABEL, hashlib.sha256).digest()
        self._clock = clock
        self._spent: dict[str, float] = {}
        self._lock = threading.Lock()

    def _mac(self, entry: TicketEntry, owner: str, client: str, expires: str, nonce: str) -> str:
        # JSON keeps field boundaries unambiguous, whatever characters an argument holds.
        covered = json.dumps(
            [_VERSION, entry.action, entry.object_id, entry.digest, owner, client, expires, nonce],
            separators=(",", ":"),
        )
        return _b64(hmac.new(self._key, covered.encode(), hashlib.sha256).digest())

    def issue(self, entry: TicketEntry, *, owner: str, client: str) -> str:
        expires = str(int(self._clock()) + TICKET_LIFETIME_SECONDS)
        nonce = secrets.token_urlsafe(12)
        return f"{_VERSION}.{expires}.{nonce}.{self._mac(entry, owner, client, expires, nonce)}"

    def verify(
        self, ticket: str, entry: TicketEntry, *, owner: str, client: str
    ) -> SpentTicket | TicketRefusal:
        """Check a ticket against the call and spend its nonce, or say why it does not hold.

        Every bound field is part of the MAC, so a ticket for another action, object, digest, owner
        or client is a `MISMATCH`, as is a changed signature.
        """

        parts = ticket.split(".") if len(ticket) <= _MAX_TICKET_CHARS else []
        if len(parts) != 4 or parts[0] != _VERSION or not parts[1].isdigit():
            return TicketRefusal.MALFORMED
        _, expires, nonce, mac = parts
        expected = self._mac(entry, owner, client, expires, nonce)
        if not hmac.compare_digest(mac.encode(), expected.encode()):
            return TicketRefusal.MISMATCH
        now = self._clock()
        if int(expires) < now:
            return TicketRefusal.EXPIRED
        with self._lock:
            self._spent = {n: until for n, until in self._spent.items() if until >= now}
            if nonce in self._spent:
                return TicketRefusal.USED
            self._spent[nonce] = float(expires)
        return SpentTicket(nonce)

    def release(self, spent: SpentTicket) -> None:
        """Give a nonce back, when the decision it was spent on failed and may be retried."""

        with self._lock:
            self._spent.pop(spent.nonce, None)

    def issue_all(
        self, entries: Iterable[TicketEntry], *, owner: str, client: str
    ) -> dict[str, str]:
        return {
            ticket_key(entry): self.issue(entry, owner=owner, client=client) for entry in entries
        }


def with_tickets(
    result: ToolResult,
    tickets: DecisionTickets | None,
    actor: Actor,
    entries: Iterable[TicketEntry],
) -> ToolResult:
    """Add the tickets for `entries` to the result's `_meta`, never to its content.

    A server built without a ticket signer (a test that registers one module) adds nothing.
    """

    issued = (
        tickets.issue_all(entries, owner=str(actor.user_id), client=request_client_id())
        if tickets is not None
        else {}
    )
    if issued:
        meta: dict[str, object] = {**(result.meta or {}), DECISION_TICKETS_META: issued}
        result.meta = meta
    return result
