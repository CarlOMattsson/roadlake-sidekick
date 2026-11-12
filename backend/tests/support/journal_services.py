"""The manual Journal services wired over one store, as the container builds them."""

from dataclasses import dataclass
from typing import Any

from sidekick.journal.application.capture import JournalCaptureService
from sidekick.journal.application.day import JournalDayService
from sidekick.journal.application.relations import JournalRelationService
from sidekick.journal.application.service import JournalService
from sidekick.journal.application.store import JournalStore
from sidekick.shared.types import Clock, CursorCodec


@dataclass(frozen=True, slots=True)
class ManualJournal:
    entries: JournalService
    capture: JournalCaptureService
    day: JournalDayService
    relations: JournalRelationService

    @classmethod
    def build(cls, store: JournalStore, clock: Clock, cursor_codec: CursorCodec) -> "ManualJournal":
        return cls(
            entries=JournalService(store, clock, cursor_codec),
            capture=JournalCaptureService(store, clock),
            day=JournalDayService(store, clock, cursor_codec),
            relations=JournalRelationService(store),
        )

    def services(self) -> tuple[Any, ...]:
        return (self.entries, self.capture, self.day, self.relations)
