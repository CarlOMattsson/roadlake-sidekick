"""Photos and their alt text are never read into memory.

The set of record kinds memory can hold is closed, and no memory code names the photo table or its
row, so a photo cannot become a memory source, a candidate or a document.
"""

from pathlib import Path

import sidekick.memory
from sidekick.memory.domain import MemoryKind

MEMORY_PACKAGE = Path(sidekick.memory.__file__).parent


def test_memory_holds_only_the_closed_set_of_record_kinds() -> None:
    assert {kind.value for kind in MemoryKind} == {"journal_entry", "contact", "project", "task"}


def test_no_memory_module_names_the_photo_table_or_row() -> None:
    sources = sorted(MEMORY_PACKAGE.rglob("*.py"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8").lower()
        assert "journal_attachment" not in text, path
        assert "journalattachment" not in text, path
