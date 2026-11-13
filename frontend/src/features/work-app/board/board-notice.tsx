import { useEffect, useRef } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { WorkLabels } from "../shared/labels";
import { boardLabelsFor } from "./board-labels";
import { writeFailure } from "../transport/transport";

/**
 * The read or write a board action runs; the view runs one read at a time, card writes queue per card. `moveAll` is
 * the agenda's bulk reschedule and the Undo of it, which have a text of their own.
 */
export type BoardAction = "move" | "moveAll" | "reload" | "more";
/** The record a failed change was made to; the agenda shows the notice in its row and names it. */
export type NoticeRow = { key: string; title: string };

/**
 * What the last board action did. `failed` names the action so retry runs it again; a conflict,
 * a refusal, invalid values or a record that no longer exists are never retried by the view itself.
 */
export type BoardNotice =
  | { kind: "conflict" }
  | {
      kind: "forbidden" | "invalid" | "not_found";
      action: BoardAction;
      row?: NoticeRow;
    }
  | { kind: "failed"; action: BoardAction; cause?: unknown; row?: NoticeRow };

export function failureNotice(
  error: unknown,
  action: BoardAction,
  row?: NoticeRow,
): BoardNotice {
  const kind = writeFailure(error);
  if (kind === "conflict") return { kind: "conflict" };
  if (kind === "failed") return { kind, action, cause: error, row };
  return { kind, action, row };
}

/**
 * Where the agenda shows a notice: in the row that was written, at "Flytta alla" for the bulk move, below "Visa fler",
 * else above the list. A conflict is the banner above the list.
 */
export function noticeSpot(notice: BoardNotice | undefined): string {
  if (!notice || notice.kind === "conflict") return "top";
  if (notice.action === "more" || notice.action === "moveAll")
    return notice.action;
  return notice.row ? `row:${notice.row.key}` : "top";
}

/**
 * The notice of a board or agenda action, with its banner focus and calm text. A failed read keeps the list and is the
 * family's refresh row (ErrorNotice): ⚠, the text and a secondary "Försök igen". A failed change is the family's write
 * error row: the line in the danger tone and "Försök igen" as a text button.
 */
export function NoticeView({
  notice,
  labels: t,
  onReload,
  onRetry,
}: {
  notice: BoardNotice | undefined;
  labels: WorkLabels;
  onReload: () => void;
  onRetry: (action: BoardAction) => void;
}) {
  const banner = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (notice?.kind === "conflict") banner.current?.focus();
  }, [notice]);
  if (!notice) return null;
  const b = boardLabelsFor(t.dateLocale);
  if (notice.kind === "conflict")
    return (
      <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
        <p>{b.conflict}</p>
        <button type="button" onClick={onReload}>
          {b.conflictAction}
        </button>
      </div>
    );
  const failed = notice.kind === "failed";
  const change =
    notice.kind === "invalid" ||
    notice.kind === "not_found" ||
    notice.action !== "reload";
  const writing = notice.action === "move" || notice.action === "moveAll";
  return (
    <ErrorNotice
      placement={change ? "row" : "refresh"}
      locale={t.dateLocale}
      cause={failed ? notice.cause : undefined}
      // A failed read of the whole list keeps the family's "Kunde inte uppdatera"; the record that is gone only explains.
      message={
        notice.kind === "forbidden"
          ? writing
            ? t.forbiddenWrite
            : b.forbidden
          : notice.kind === "invalid"
            ? t.invalidChange
            : notice.kind === "not_found"
              ? t.notFound
              : notice.action === "move"
                ? notice.row
                  ? b.rowChangeFailed(notice.row.title)
                  : b.moveFailed
                : notice.action === "moveAll"
                  ? t.moveAllFailed
                  : notice.action === "more"
                    ? b.moreFailed
                    : undefined
      }
      onRetry={failed ? () => onRetry(notice.action) : undefined}
    />
  );
}
