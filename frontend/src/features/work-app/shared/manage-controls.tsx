import { useEffect, useRef } from "react";
import { UndoNotice } from "../../mcp-apps/ui/notice";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { ManageLabels } from "./manage-labels";
import type { WriteFailure } from "../transport/transport";
import "./manage.css";

/** The order a list has after the item at `index` moves by `delta` places; undefined at an edge. */
export function moveItem<T>(
  list: readonly T[],
  index: number,
  delta: -1 | 1,
): T[] | undefined {
  const target = index + delta;
  if (index < 0 || index >= list.length) return undefined;
  if (target < 0 || target >= list.length) return undefined;
  const next = [...list];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item as T);
  return next;
}

type Control = "up" | "down" | "archive";

/**
 * Moves focus to one control of a row after a write. The row may have moved, so the control is found
 * by its id, not by position. If the wanted control is disabled (the row is now first or last), its
 * sibling that moves the other way takes the focus, so the keyboard user can keep going.
 */
export function focusControl(
  container: HTMLElement | null,
  id: string,
  prefer: Control,
): void {
  if (!container) return;
  const find = (control: Control) =>
    container.querySelector<HTMLButtonElement>(
      `[data-manage="${CSS.escape(id)}:${control}"]`,
    );
  const order: Control[] =
    prefer === "up"
      ? ["up", "down", "archive"]
      : prefer === "down"
        ? ["down", "up", "archive"]
        : ["archive", "up", "down"];
  for (const control of order) {
    const button = find(control);
    if (button && !button.disabled) {
      button.focus();
      return;
    }
  }
}

/**
 * Moves focus to the Undo button of an UndoLine drawn inside `box`, the one rule every list follows
 * after an archive or an unlink. Returns false while no such line is drawn, so a caller can wait.
 */
export function focusUndoIn(box: HTMLElement | null): boolean {
  const button = box?.querySelector<HTMLButtonElement>("button");
  if (!button) return false;
  button.focus();
  return true;
}

/**
 * The visible controls of one row in an ordered list: Up, Down and Archive. They are plain buttons
 * (no menu, no drag needed); each carries the item's title in its accessible name, so a screen reader
 * hears which row it acts on. Up is disabled on the first row and Down on the last.
 */
export function RowControls({
  id,
  title,
  index,
  count,
  disabled,
  labels,
  onMove,
  onArchive,
}: {
  id: string;
  title: string;
  index: number;
  count: number;
  disabled: boolean;
  labels: ManageLabels;
  /** Absent: no Up and Down (the host cannot reorder). */
  onMove?: (delta: -1 | 1) => void;
  /** Absent: no Archive (the host cannot archive). */
  onArchive?: () => void;
}) {
  return (
    <div className="work-manage-controls">
      {onMove && (
        <>
          <button
            type="button"
            data-manage={`${id}:up`}
            aria-label={labels.moveUpFor(title)}
            disabled={disabled || index === 0}
            onClick={() => onMove(-1)}
          >
            <span aria-hidden="true">↑ </span>
            {labels.up}
          </button>
          <button
            type="button"
            data-manage={`${id}:down`}
            aria-label={labels.moveDownFor(title)}
            disabled={disabled || index === count - 1}
            onClick={() => onMove(1)}
          >
            <span aria-hidden="true">↓ </span>
            {labels.down}
          </button>
        </>
      )}
      {onArchive && (
        <button
          type="button"
          data-manage={`${id}:archive`}
          aria-label={labels.archiveFor(title)}
          disabled={disabled}
          onClick={onArchive}
        >
          {labels.archive}
        </button>
      )}
    </div>
  );
}

/**
 * Items archived during this visit, each with a visible Restore button. The servers list only active
 * Steps and Actions, so this is where an archive is taken back after the Undo line has gone.
 */
export function ArchivedRows({
  items,
  disabled,
  labels,
  onRestore,
}: {
  items: readonly { id: string; title: string }[];
  disabled: boolean;
  labels: ManageLabels;
  onRestore: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section
      className="work-manage-archived"
      aria-label={labels.archivedHeading(items.length)}
    >
      <p className="work-manage-archived-heading">
        {labels.archivedHeading(items.length)}
      </p>
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <span className="work-manage-archived-title">{item.title}</span>
            <button
              type="button"
              data-manage={`${item.id}:restore`}
              aria-label={labels.restoreFor(item.title)}
              disabled={disabled}
              onClick={() => onRestore(item.id)}
            >
              {labels.restore}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The calm message under a list after a refused write. A conflict is announced and takes focus, and
 * offers a re-read; a retryable failure offers the same write again; the others only explain.
 */
export function WriteNotice({
  failure,
  labels,
  onReload,
  onRetry,
}: {
  failure: WriteFailure | undefined;
  labels: ManageLabels;
  onReload: () => void;
  onRetry?: () => void;
}) {
  const banner = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (failure === "conflict") banner.current?.focus();
  }, [failure]);
  if (!failure) return null;
  if (failure === "conflict" || failure === "invalid")
    return (
      <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
        <p>{failure === "conflict" ? labels.conflict : labels.invalid}</p>
        <button type="button" onClick={onReload}>
          {labels.reload}
        </button>
      </div>
    );
  // The record is gone or not yours to change: the text only explains, with no retry button.
  const message =
    failure === "forbidden"
      ? labels.forbidden
      : failure === "not_found"
        ? labels.notFound
        : labels.failed;
  return (
    <ErrorNotice
      placement="row"
      locale={labels.dateLocale}
      message={message}
      onRetry={failure === "failed" ? onRetry : undefined}
    />
  );
}

/**
 * A one-line notice after a reversible change with a visible Undo: the family's Undo notice
 * (notice.tsx), not sticky, since it sits under the list it changed. The text is announced politely;
 * the button is disabled while the undo write runs. Nothing is shown before the change is saved.
 */
export function UndoLine({
  text,
  disabled,
  labels,
  onUndo,
}: {
  text: string;
  disabled: boolean;
  labels: ManageLabels;
  onUndo: () => void;
}) {
  return (
    <UndoNotice
      message={text}
      undoLabel={labels.undo}
      onUndo={onUndo}
      busy={disabled}
      sticky={false}
      className="work-manage-undo"
    />
  );
}
