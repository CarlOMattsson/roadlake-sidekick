"""The store is composed from one mixin per context; two mixins must never share a public name.

Python resolves a repeated name silently to the first class in the order, so a second definition
would change behaviour without any failure.
"""

from collections import defaultdict

from sidekick.store import SqlAlchemyStore


def test_no_two_store_mixins_define_the_same_public_name() -> None:
    owners: dict[str, list[str]] = defaultdict(list)
    for cls in SqlAlchemyStore.__mro__[1:]:
        if cls is object:
            continue
        for name in vars(cls):
            if not name.startswith("_"):
                owners[name].append(cls.__name__)

    assert owners
    assert {name: classes for name, classes in owners.items() if len(classes) > 1} == {}
