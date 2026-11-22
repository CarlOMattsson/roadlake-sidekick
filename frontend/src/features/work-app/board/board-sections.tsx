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
 * The count of one section of the single layout, as its heading and its column tab say it: where the cards are now. A
 * card standing in a section for its Ångra counts in the section it went to at once, not in the one it stands in; the
 * records not read yet (`unshown`) count too.
 */
export function sectionCount({
  segment,
  items,
  shown,
  undos,
  unshown,
}: {
  segment: BoardSegment;
  items: WorkItemRecord[];
  shown: WorkItemRecord[];
  undos: Record<string, BoardUndo>;
  unshown: number;
}): number {
  const kept = Object.values(undos).filter(
    (entry) =>
      entry.at === segment.key &&
      !items.some((item) => cardKey(item) === entry.key),
  ).length;
  const away = items.filter(
    (item) => (undos[cardKey(item)]?.at ?? segment.key) !== segment.key,
  ).length;
  return shown.length - kept + away + unshown;
}

/**
 * One status section of the single layout (a phone): its heading with the count (Klar folded until opened,
 * designsystem §3 "Chevronregeln") and its cards, drawn by `renderCard`. `items` are the section's records (its
 * count), `shown` the cards it draws.
 */
export function SingleSection({
  segment,
  items,
  shown,
  drawn = shown,
  needle,
  undos,
  doneOpen,
  onToggleDone,
  completeColumn,
  renderCard,
  more,
  unshown = 0,
  tabbed = false,
  emptyText,
}: {
  segment: BoardSegment;
  items: WorkItemRecord[];
  shown: WorkItemRecord[];
  /** The cards of `shown` the section draws; the rest wait behind its "Visa N till". All of them when absent. */
  drawn?: WorkItemRecord[];
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
  /** The section's "Visa fler", last under its cards; absent when the section is whole on the board. */
  more?: ReactNode;
  /** The section's records not read yet (the server's totals), counted in its heading. */
  unshown?: number;
  /** The section is the chosen column tab: its heading is left to the tab (kept for screen readers), Klar does not fold. */
  tabbed?: boolean;
  /** What a chosen tab with no card says. */
  emptyText?: string;
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
  const count = sectionCount({ segment, items, shown, undos, unshown });
  // A section with no card of its own still shows when its count is above 0: a card that went here stands
  // in its old section for its Ångra, and the new number must be seen where the card went. The chosen tab always shows.
  if (!tabbed && !shown.length && count <= 0 && !more) return null;
  const heading = `${segment.label} (${count})`;
  // Under the column tabs Klar is the tab the owner chose: it opens at once, and the tab already names it and its count.
  const folds = status === "completed" && !tabbed;
  return (
    <section
      className="work-column"
      aria-label={segment.label}
      data-board-column={segment.key}
    >
      <h3 className={tabbed ? "work-visually-hidden" : undefined}>
        {folds ? (
          <Fold text={heading} open={doneOpen} onToggle={onToggleDone} />
        ) : (
          <Counted text={heading} />
        )}
      </h3>
      {folds && !doneOpen ? null : (
        <>
          {drawn.length ? (
            <ul className="work-list">
              {drawn.map((item, at) => renderCard(item, at, shown, orderable))}
            </ul>
          ) : tabbed && !more && count <= 0 ? (
            <p className="work-column-empty">{emptyText}</p>
          ) : null}
          {more}
        </>
      )}
    </section>
  );
}

/** One status column of the columns layout: its heading with the count, its cards (drawn by `renderCard`) and the drop mark. */
export function ColumnSection({
  segment,
  items,
  drawn,
  target,
  emptyText,
  renderCard,
  more,
  unshown = 0,
}: {
  segment: BoardSegment;
  items: { item: WorkItemRecord }[];
  /** The cards of `items` the column draws; the rest wait behind its "Visa N till". */
  drawn: WorkItemRecord[];
  /** The drag is over this column. */
  target: boolean;
  emptyText: string;
  renderCard: (item: WorkItemRecord) => ReactNode;
  /** The column's "Visa fler", right under its last card; absent when the column is whole on the board. */
  more?: ReactNode;
  /** The column's records not read yet (the server's totals), counted in its heading. */
  unshown?: number;
}) {
  return (
    <section
      className="work-column"
      aria-label={segment.label}
      data-board-column={segment.key}
      style={target ? dropTargetStyle : undefined}
    >
      <h3>
        {segment.label} ({items.length + unshown})
      </h3>
      {items.length ? (
        <ul className="work-list">{drawn.map((item) => renderCard(item))}</ul>
      ) : more ? null : (
        <p>{emptyText}</p>
      )}
      {more}
    </section>
  );
}

/** A circular arrow, the icon of every refresh button. Decorative: the button's label names the action. */
export function RefreshIcon() {
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
