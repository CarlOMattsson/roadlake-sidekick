import { useEffect, useRef } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { WorkLabels } from "../shared/labels";
import { writeFailure } from "../transport/transport";

/** The read or write a board action runs; the view runs one read at a time, card writes queue per card. */
export type BoardAction = "move" | "reload" | "more";
/**
 * What the last board action did. `failed` names the action so retry runs it again; a conflict,
 * a refusal, invalid values or a record that no longer exists are never retried by the view itself.
 */
export type BoardNotice =
  | { kind: "conflict" }
  | { kind: "forbidden"; action: BoardAction }
  | { kind: "invalid" }
  | { kind: "not_found" }
  | { kind: "failed"; action: BoardAction; cause?: unknown };

export function failureNotice(
  error: unknown,
  action: BoardAction,
): BoardNotice {
  const kind = writeFailure(error);
  if (kind === "conflict") return { kind: "conflict" };
  if (kind === "forbidden") return { kind: "forbidden", action };
  if (kind === "invalid") return { kind: "invalid" };
  if (kind === "not_found") return { kind: "not_found" };
  return { kind: "failed", action, cause: error };
}

/**
 * The notice of a board or agenda action, with its banner focus and calm text. Every notice but the conflict is the
 * family's refresh row (ErrorNotice): ⚠, the text and, for a failure that can be repeated, a secondary "Försök igen".
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
  if (notice.kind === "conflict")
    return (
      <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
        <p>{t.boardConflict}</p>
        <button type="button" onClick={onReload}>
          {t.reload}
        </button>
      </div>
    );
  const failed = notice.kind === "failed";
  return (
    <ErrorNotice
      placement="refresh"
      locale={t.dateLocale}
      cause={failed ? notice.cause : undefined}
      // A failed read keeps the family's "Kunde inte uppdatera"; the record that is gone only explains.
      message={
        notice.kind === "forbidden"
          ? notice.action === "move"
            ? t.forbiddenWrite
            : t.boardForbidden
          : notice.kind === "invalid"
            ? t.invalidChange
            : notice.kind === "not_found"
              ? t.notFound
              : notice.action === "move"
                ? t.moveFailed
                : undefined
      }
      onRetry={failed ? () => onRetry(notice.action) : undefined}
    />
  );
}
