import type { ReactNode } from "react";
import type { WorkLabels } from "../../shared/labels";
import { BoardCard } from "../board-card";
import { boardLabelsFor } from "../board-labels";
import { ColumnSection, SingleSection } from "../board-sections";
import type { BoardUndo } from "../board-columns";
import type { BoardDragState } from "../board-drag";
import type { dragHandle } from "../board-handle";
import { cardKey, type BoardSegment } from "../../shared/work-items";
import type {
  TaskStatusValue,
  WorkBoardPlacementItem,
  WorkFrame,
  WorkItemRecord,
} from "../../transport/transport";

type Queue = { queued: boolean; busy: boolean };

/** What both layouts draw a card with. */
type CardProps = {
  labels: WorkLabels;
  disabled: boolean;
  now: Date;
  onOpen: (frame: WorkFrame) => void;
  onMove: (card: WorkItemRecord, to: TaskStatusValue) => void;
  undoOf: (item: WorkItemRecord) => ReactNode;
  queueOf: (item: WorkItemRecord) => Queue;
};

/** The single layout (a phone): every status as a section, Klar folded, a check on each card. */
export function SingleLayout({
  sections,
  needle,
  undos,
  doneOpen,
  onToggleDone,
  completeColumn,
  taskTitle,
  toggleDone,
  toggleStep,
  stepWithin,
  labels: t,
  disabled,
  now,
  onOpen,
  onMove,
  undoOf,
  queueOf,
}: CardProps & {
  sections: {
    segment: BoardSegment;
    items: WorkItemRecord[];
    shown: WorkItemRecord[];
  }[];
  needle: string;
  undos: Record<string, BoardUndo>;
  doneOpen: boolean;
  onToggleDone: () => void;
  completeColumn: (
    status: TaskStatusValue,
  ) => WorkBoardPlacementItem[] | undefined;
  /** The title of the Task with this id, for the Step rows that name their parent. */
  taskTitle: (id: string) => string | undefined;
  toggleDone: (card: WorkItemRecord) => void;
  toggleStep: (card: WorkItemRecord) => void;
  stepWithin: (card: WorkItemRecord, direction: -1 | 1) => void;
}) {
  return sections.map(({ segment, items, shown }) => (
    <SingleSection
      key={segment.key}
      segment={segment}
      items={items}
      shown={shown}
      needle={needle}
      undos={undos}
      doneOpen={doneOpen}
      onToggleDone={onToggleDone}
      completeColumn={completeColumn}
      renderCard={(item, at, all, orderable) => (
        <BoardCard
          key={cardKey(item)}
          item={item}
          labels={t}
          layout="single"
          disabled={disabled}
          dragging={false}
          onOpen={onOpen}
          onMove={onMove}
          onToggleDone={item.kind === "step" ? toggleStep : toggleDone}
          onReorder={orderable ? stepWithin : undefined}
          canMoveUp={at > 0}
          canMoveDown={at < all.length - 1}
          now={now}
          undo={undoOf(item)}
          nested={
            item.kind === "step" && all.some((task) => task.id === item.task_id)
          }
          parentTitle={
            item.kind === "step" && item.task_id
              ? taskTitle(item.task_id)
              : undefined
          }
          {...queueOf(item)}
        />
      )}
    />
  ));
}

/** The columns layout: one column per status side by side, the cards draggable by their handle. */
export function ColumnsLayout({
  columns,
  drag,
  handleFor,
  labels: t,
  disabled,
  now,
  onOpen,
  onMove,
  undoOf,
  queueOf,
}: CardProps & {
  columns: { segment: BoardSegment; items: { item: WorkItemRecord }[] }[];
  drag: BoardDragState;
  handleFor: (item: WorkItemRecord) => ReturnType<typeof dragHandle>;
}) {
  return columns.map(({ segment, items }) => (
    <ColumnSection
      key={segment.key}
      segment={segment}
      items={items}
      target={drag.phase === "dragging" && drag.column === segment.key}
      emptyText={boardLabelsFor(t.dateLocale).noCards}
      renderCard={(item) => (
        <BoardCard
          key={cardKey(item)}
          item={item}
          labels={t}
          disabled={disabled}
          dragging={drag.phase === "dragging" && drag.taskId === item.id}
          onOpen={onOpen}
          onMove={onMove}
          drag={handleFor(item)}
          now={now}
          undo={undoOf(item)}
          {...queueOf(item)}
        />
      )}
    />
  ));
}
