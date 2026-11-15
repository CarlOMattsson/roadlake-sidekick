"""The reviewed mapping from a webhook scope to application permission.

A webhook token holds webhook scopes, never application scopes. Each `/webhooks/v1/` route names
one operation below; the route checks the token's scope and then calls one fixed use case with an
actor that carries exactly that operation's application scopes, for that one call. So
`webhook:shopping:add` can add Shopping items and read the owner's list names to find the default
list, and `webhook:tasks:create` can create a Task; neither can read an item, a Task title, or
change or remove anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from sidekick.shared.errors.core import PermissionDeniedError
from sidekick.shared.types import Actor
from sidekick.webhooks.tokens import WEBHOOK_SHOPPING_ADD, WEBHOOK_TASKS_CREATE, WebhookCredential


@dataclass(frozen=True, slots=True)
class WebhookOperation:
    name: str
    scope: str
    application_scopes: frozenset[str]
    # One plain sentence for the operator's scope reference.
    description: str


# `shopping:read` is for finding the oldest active list when the call names none.
SHOPPING_ITEM_ADD = WebhookOperation(
    "shopping.item_add",
    WEBHOOK_SHOPPING_ADD,
    frozenset({"shopping:read", "shopping:write"}),
    "Add one item to a shopping list, the oldest active list when none is named.",
)
TASK_CREATE = WebhookOperation(
    "task.create",
    WEBHOOK_TASKS_CREATE,
    frozenset({"tasks:write"}),
    "Create one task with a title and an optional due date.",
)

OPERATIONS: tuple[WebhookOperation, ...] = (SHOPPING_ITEM_ADD, TASK_CREATE)


class WebhookScopeMissing(PermissionDeniedError):
    """The token was not granted the scope this operation needs."""


def operation_actor(credential: WebhookCredential, operation: WebhookOperation) -> Actor:
    """The actor for one call of `operation`, or `WebhookScopeMissing`."""

    if operation.scope not in credential.scopes:
        raise WebhookScopeMissing(operation.name)
    return Actor(credential.user_id, operation.application_scopes)
