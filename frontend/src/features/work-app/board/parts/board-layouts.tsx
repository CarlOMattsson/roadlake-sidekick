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
  /**
   * The "Visa N till" of one column or section, last under its cards: `hidden` are the cards it holds back. Null when
   * nothing is held back and the column is whole on the board.
   */
  moreFor: (segment: BoardSegment, hidden: WorkItemRecord[]) => ReactNode;
};

/** The single layout (a phone): every status as a section, Klar folded, a check on each card. */
export function SingleLayout({
  sections,
  needle,
  undos,
  doneOpen,
  onToggleDone,
  completeColumn,
  toggleDone,
  stepWithin,
  labels: t,
  disabled,
  now,
  onOpen,
  onMove,
  undoOf,
  queueOf,
  moreFor,
  chosen,
}: CardProps & {
  sections: {
    segment: BoardSegment;
    items: WorkItemRecord[];
    shown: WorkItemRecord[];
    drawn: WorkItemRecord[];
    hidden: WorkItemRecord[];
    unshown: number;
  }[];
  needle: string;
  undos: Record<string, BoardUndo>;
  doneOpen: boolean;
  onToggleDone: () => void;
  completeColumn: (
    status: TaskStatusValue,
  ) => WorkBoardPlacementItem[] | undefined;
  toggleDone: (card: WorkItemRecord) => void;
  stepWithin: (card: WorkItemRecord, direction: -1 | 1) => void;
  /** The column tab chosen (see ColumnTabs): only its section is drawn. Undefined draws every section (a search). */
  chosen?: string;
}) {
  const words = boardLabelsFor(t.dateLocale);
  const chosenSections =
    chosen === undefined
      ? sections
      : sections.filter(({ segment }) => segment.key === chosen);
  return chosenSections.map(
    ({ segment, items, shown, drawn, hidden, unshown }) => (
      <SingleSection
        key={segment.key}
        tabbed={chosen !== undefined}
        emptyText={words.noCards}
        segment={segment}
        items={items}
        shown={shown}
        drawn={drawn}
        needle={needle}
        undos={undos}
        doneOpen={doneOpen}
        onToggleDone={onToggleDone}
        completeColumn={completeColumn}
        more={moreFor(segment, hidden)}
        unshown={unshown}
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
            onToggleDone={toggleDone}
            onReorder={orderable ? stepWithin : undefined}
            canMoveUp={at > 0}
            canMoveDown={at < all.length - 1}
            now={now}
            undo={undoOf(item)}
            {...queueOf(item)}
          />
        )}
      />
    ),
  );
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
  moreFor,
}: CardProps & {
  columns: {
    segment: BoardSegment;
    items: { item: WorkItemRecord }[];
    drawn: WorkItemRecord[];
    hidden: WorkItemRecord[];
    unshown: number;
  }[];
  drag: BoardDragState;
  handleFor: (item: WorkItemRecord) => ReturnType<typeof dragHandle>;
}) {
  return columns.map(({ segment, items, drawn, hidden, unshown }) => (
    <ColumnSection
      key={segment.key}
      segment={segment}
      items={items}
      drawn={drawn}
      target={drag.phase === "dragging" && drag.column === segment.key}
      emptyText={boardLabelsFor(t.dateLocale).noCards}
      more={moreFor(segment, hidden)}
      unshown={unshown}
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
