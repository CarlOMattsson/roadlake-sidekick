import type { CSSProperties, ReactNode } from "react";
import { Counted } from "../../mcp-apps/ui/count";
import { Fold } from "../../mcp-apps/ui/fold";
import { cardKey, type BoardSegment } from "../shared/work-items";
import { isTaskStatus } from "../transport/transport";
import type {
  TaskStatusValue,
  WorkBoardPlacementItem,
  WorkItemRecord,
} from "../transport/transport";
import type { BoardUndo } from "./board-columns";

const dropTargetStyle: CSSProperties = {
  outline: "2px dashed currentColor",
  outlineOffset: 2,
};

/**
 * One status section of the single layout (a phone): its heading with the count (Klar folded until opened,
 * designsystem §3 "Chevronregeln") and its cards, drawn by `renderCard`. `items` are the section's records (its
 * count), `shown` the cards it draws.
 */
export function SingleSection({
  segment,
  items,
  shown,
  needle,
  undos,
  doneOpen,
  onToggleDone,
  completeColumn,
  renderCard,
}: {
  segment: BoardSegment;
  items: WorkItemRecord[];
  shown: WorkItemRecord[];
  needle: string;
  undos: Record<string, BoardUndo>;
  doneOpen: boolean;
  onToggleDone: () => void;
  completeColumn: (
    status: TaskStatusValue,
  ) => WorkBoardPlacementItem[] | undefined;
  renderCard: (
    item: WorkItemRecord,
    at: number,
    shown: WorkItemRecord[],
    orderable: boolean,
  ) => ReactNode;
}) {
  const status = isTaskStatus(segment.key) ? segment.key : undefined;
  // Flytta upp and Flytta ned exist only for a column that is whole on the board, shown unfiltered, and listed
  // in the column's order: a row kept here for its Ångra may stand elsewhere in the column.
  const whole =
    !needle && status !== undefined ? completeColumn(status) : undefined;
  const orderable =
    whole !== undefined &&
    whole.length === shown.length &&
    whole.every((item, at) => item.taskId === shown[at]?.id);
  // The count says where the cards are now (a card standing
  // here for its Ångra counts in the section it went to at once, not in the one it stands in.
  const kept = Object.values(undos).filter(
    (entry) =>
      entry.at === segment.key &&
      !items.some((item) => cardKey(item) === entry.key),
  ).length;
  const away = items.filter(
    (item) => (undos[cardKey(item)]?.at ?? segment.key) !== segment.key,
  ).length;
  const count = shown.length - kept + away;
  // A section with no card of its own still shows when its count is above 0: a card that went here stands
  // in its old section for its Ångra, and the new number must be seen where the card went.
  if (!shown.length && count <= 0) return null;
  const heading = `${segment.label} (${count})`;
  const folds = status === "completed";
  return (
    <section
      className="work-column"
      aria-label={segment.label}
      data-board-column={segment.key}
    >
      <h3>
        {folds ? (
          <Fold text={heading} open={doneOpen} onToggle={onToggleDone} />
        ) : (
          <Counted text={heading} />
        )}
      </h3>
      {(folds && !doneOpen) || !shown.length ? null : (
        <ul className="work-list">
          {shown.map((item, at) => renderCard(item, at, shown, orderable))}
        </ul>
      )}
    </section>
  );
}

/** One status column of the columns layout: its heading with the count, its cards (drawn by `renderCard`) and the drop mark. */
export function ColumnSection({
  segment,
  items,
  target,
  emptyText,
  renderCard,
}: {
  segment: BoardSegment;
  items: { item: WorkItemRecord }[];
  /** The drag is over this column. */
  target: boolean;
  emptyText: string;
  renderCard: (item: WorkItemRecord) => ReactNode;
}) {
  return (
    <section
      className="work-column"
      aria-label={segment.label}
      data-board-column={segment.key}
      style={target ? dropTargetStyle : undefined}
    >
      <h3>
        {segment.label} ({items.length})
      </h3>
      {items.length ? (
        <ul className="work-list">
          {items.map(({ item }) => renderCard(item))}
        </ul>
      ) : (
        <p>{emptyText}</p>
      )}
    </section>
  );
}

/** A circular arrow, the icon of the board refresh. Decorative: the button's label names the action. */
function RefreshIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 4v5h-5" />
    </svg>
  );
}

/** The board's own `refresh` button: the refresh glyph and its text. */
export function RefreshButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="work-icon-button work-refresh-text"
      disabled={disabled}
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <RefreshIcon />
      <span>{label}</span>
    </button>
  );
}
