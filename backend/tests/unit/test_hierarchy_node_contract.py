"""The keys of a Work hierarchy node are a client contract: Android and MCP clients read them."""

from uuid import UUID

from sidekick.structured.work_records import HierarchyNodeRecord
from sidekick.work.application.models import HierarchyNode

NODE_KEYS = ["kind", "id", "parent_id", "title", "status", "version", "accent"]
DOMAIN_ID = UUID("0192f1a0-0000-7000-8000-0000000000d1")
PROJECT_ID = UUID("0192f1a0-0000-7000-8000-0000000000a1")


def test_a_domain_node_sends_exactly_these_keys_and_values() -> None:
    node = HierarchyNode(
        kind="domain",
        id=DOMAIN_ID,
        parent_id=None,
        title="Hälsa",
        status="active",
        version=3,
        accent="sage",
    )

    assert node.to_data() == {
        "kind": "domain",
        "id": DOMAIN_ID,
        "parent_id": None,
        "title": "Hälsa",
        "status": "active",
        "version": 3,
        "accent": "sage",
    }
    assert list(node.to_data()) == NODE_KEYS


def test_a_node_without_an_accent_still_sends_the_accent_key() -> None:
    node = HierarchyNode(
        kind="project",
        id=PROJECT_ID,
        parent_id=DOMAIN_ID,
        title="Renovering",
        status="active",
        version=1,
    )

    assert list(node.to_data()) == NODE_KEYS
    assert node.to_data()["accent"] is None


def test_the_structured_record_carries_the_same_keys_as_the_node() -> None:
    node = HierarchyNode(
        kind="process",
        id=PROJECT_ID,
        parent_id=DOMAIN_ID,
        title="Veckoplan",
        status="active",
        version=2,
    )

    record = HierarchyNodeRecord.model_validate(node.to_data())

    assert list(HierarchyNodeRecord.model_fields) == NODE_KEYS
    assert record.model_dump(mode="json") == {
        "kind": "process",
        "id": str(PROJECT_ID),
        "parent_id": str(DOMAIN_ID),
        "title": "Veckoplan",
        "status": "active",
        "version": 2,
        "accent": None,
    }
