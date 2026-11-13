import { useEffect, useRef } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { ShoppingLabels } from "../labels";
import type { ShoppingItem } from "../transport";

/**
 * The notice after a refused write or a failed read. In the card it is the full message with "Try again" (when the
 * write can be repeated) and "Refresh" on their own row under it. For the bought mark of one row (`brief`) it is
 * the family's one-line row error with "Try again" as a text button, and "Refresh" beside it as the second one.
 * It takes focus when it appears, so the user lands on it where it is shown.
 */
export function FailureNotice({
  labels: t,
  retry,
  busy,
  placement,
  brief,
  onRefresh,
}: {
  labels: ShoppingLabels;
  retry?: () => void;
  busy: boolean;
  /** "row" when the failed write belongs to one row; "card" for the list-level notice. */
  placement: "row" | "card";
  /** The row whose bought mark failed: the short line naming it instead of the full message. */
  brief?: ShoppingItem;
  onRefresh: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.focus();
  }, []);
  if (brief)
    return (
      <div tabIndex={-1} ref={box} className="shopping-failure">
        <ErrorNotice
          locale={t.dateLocale}
          placement="row"
          // The item still holds the state before the tap, so what failed is the other one.
          message={t.markFailed(brief.name, !brief.purchased)}
          onRetry={retry}
          retrying={busy}
        >
          <button
            type="button"
            className="sk-error-retry sk-error-retry--text"
            onClick={onRefresh}
            disabled={busy}
          >
            {t.refresh}
          </button>
        </ErrorNotice>
      </div>
    );
  return (
    <div
      role="alert"
      tabIndex={-1}
      ref={box}
      className={`shopping-failure sk-error sk-error--${placement}`}
    >
      <p>{t.failed}</p>
      <div className="shopping-failure-actions">
        {retry && (
          <button type="button" onClick={() => retry()} disabled={busy}>
            {t.retry}
          </button>
        )}
        <button type="button" onClick={onRefresh} disabled={busy}>
          {t.refresh}
        </button>
      </div>
    </div>
  );
}
