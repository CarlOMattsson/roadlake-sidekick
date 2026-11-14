"""Each context's store is built from that context's own operations, never another's.

A store holds one class per group of its context's operations. Python resolves a repeated name
silently to the first class in the order, so a second definition would change behaviour without any
failure; and a store that inherited a class of another context would bring back the combined store.
Reads a context borrows from another are delegated to ports and are defined on the store itself.
"""

from collections import defaultdict

import pytest

from sidekick.contacts.persistence import SqlContactStore
from sidekick.journal.persistence.store import SqlJournalStore
from sidekick.tasks.persistence import SqlTaskStore
from sidekick.work.persistence.store import SqlWorkStore
from sidekick.work.persistence.tags import WorkTagStore

STORES = {
    SqlContactStore: "sidekick.contacts",
    SqlJournalStore: "sidekick.journal",
    SqlTaskStore: "sidekick.tasks",
    SqlWorkStore: "sidekick.work",
    WorkTagStore: "sidekick.work",
}
SHARED_PARTS = ("sidekick.shared.", "sidekick.work.persistence.tags")
"""The shared base and the tag relay, which every store that owns tagged records mixes in."""


def _classes(store: type) -> list[type]:
    return [cls for cls in store.__mro__[1:] if cls is not object]


@pytest.mark.parametrize("store", STORES)
def test_no_two_classes_of_a_store_define_the_same_public_name(store: type) -> None:
    owners: dict[str, list[str]] = defaultdict(list)
    for cls in _classes(store):
        for name in vars(cls):
            if not name.startswith("_"):
                owners[name].append(cls.__name__)

    assert owners
    assert {name: classes for name, classes in owners.items() if len(classes) > 1} == {}


@pytest.mark.parametrize(("store", "context"), STORES.items())
def test_a_store_inherits_only_its_own_contexts_operations(store: type, context: str) -> None:
    foreign = [
        cls.__qualname__
        for cls in _classes(store)
        if not cls.__module__.startswith((context, *SHARED_PARTS))
    ]

    assert foreign == []
