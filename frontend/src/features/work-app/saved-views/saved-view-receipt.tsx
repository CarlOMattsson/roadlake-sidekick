import { useState } from "react";

import { useSingleFlight } from "../shared/use-single-flight";
import "./saved-views.css";

/**
 * The quiet line under the tab row that names the saved view the tab shows ("Visar vyn …") and offers the way back to
 * the tab's own list ("Visa allt"). It is a status region that stays mounted, so a new name is announced; with no text
 * it takes no room. `onClear` resolves whether the tab shows its own list now; when it does not, the line says so.
 */
export function SavedViewReceipt({
  text,
  clearLabel,
  failedText,
  onClear,
}: {
  text: string | undefined;
  clearLabel: string;
  failedText: string;
  onClear: () => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const flight = useSingleFlight();
  async function clear() {
    // A second press before the button re-renders disabled must not clear twice.
    if (!flight.enter()) return;
    setBusy(true);
    setFailed(false);
    try {
      setFailed(!(await onClear()));
    } finally {
      flight.leave();
      setBusy(false);
    }
  }
  return (
    <p role="status" className="work-saved-view-receipt">
      {text}
      {text === undefined ? null : (
        <button
          type="button"
          className="sk-btn--quiet"
          disabled={busy}
          onClick={() => void clear()}
        >
          {clearLabel}
        </button>
      )}
      {text !== undefined && failed ? (
        <span className="work-saved-view-receipt-failed">{failedText}</span>
      ) : null}
    </p>
  );
}
