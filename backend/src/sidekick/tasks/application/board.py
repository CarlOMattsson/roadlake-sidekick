"""Manual board order of the Tasks in one status column."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import Actor, Clock, TxSession
from sidekick.tasks.application.models import MAX_BOARD_COLUMN_REORDER, BoardPlacement
from sidekick.tasks.application.store import TaskStore
from sidekick.tasks.domain import TaskStatus


class TaskBoardService:
    def __init__(self, store: TaskStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def reorder_board_column(
        self,
        actor: Actor,
        status: TaskStatus,
        *,
        items: Sequence[tuple[UUID, int]],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Sequence[BoardPlacement]:
        """Persist a complete manual order for one owner-scoped board column."""

        actor.require("tasks:write")
        if not items:
            raise ValidationError("board reorder must contain at least one task")
        if len(items) > MAX_BOARD_COLUMN_REORDER:
            raise ValidationError("board reorder exceeds the supported item count")
        if len({item_id for item_id, _ in items}) != len(items):
            raise ValidationError("board reorder must list every task exactly once")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.list_board_column_tasks(
                session, actor.user_id, status, MAX_BOARD_COLUMN_REORDER + 1
            )
            if len(current) > MAX_BOARD_COLUMN_REORDER:
                raise ValidationError("board column is too large to reorder")
            if {task.id for task in current} != {item_id for item_id, _ in items}:
                raise ValidationError("board reorder must include every active task exactly once")
            by_id = {task.id: task for task in current}
            placements: list[dict[str, Any]] = []
            for position, (item_id, version) in enumerate(items, start=1):
                task = by_id[item_id]
                if task.version != version:
                    raise ConflictError("stale task board order")
                ranked = task.rank_on_board(position=position, now=self.clock.now())
                if ranked is not task:
                    self.store.save_task(session, ranked, expected_version=version)
                placements.append(
                    {
                        "task_id": str(ranked.id),
                        "board_rank": position,
                        "version": ranked.version,
                    }
                )
            # Content-free: the event names the owner and the correlation id only. No task id,
            # title or column contents are copied into the audit row. It sits inside the
            # idempotent `execute`, so a replay returns the record without a second event.
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="task.board_reordered",
                outcome="success",
                target_type="task_board",
                correlation_id=correlation_id,
            )
            return {"items": placements}

        result = self.store.transaction(
            lambda session: self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reorder_board_column",
                key=idempotency_key,
                payload={
                    "status": status.value,
                    "items": [[str(item_id), version] for item_id, version in items],
                },
                execute=lambda: operation(session),
            )
        )
        return [
            BoardPlacement(UUID(item["task_id"]), item["board_rank"], item["version"])
            for item in result["items"]
        ]
