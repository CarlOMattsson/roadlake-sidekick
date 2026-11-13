import { useEffect, useRef } from "react";
import type { WorkLabels } from "../shared/labels";

/**
 * What the Contact view shows after Archive: the receipt, the one fact that archived Contacts are read-only, and Ångra, which
 * restores the Contact at the version the archive left. The button takes the focus when the receipt appears, so the keyboard
 * stays on the page. A failed Ångra is shown by the page's write-failure line, whose Retry reuses the key.
 */
export function ContactArchived({
  labels: t,
  busy,
  onRestore,
}: {
  labels: WorkLabels;
  busy: boolean;
  onRestore: () => void;
}) {
  const undo = useRef<HTMLButtonElement>(null);
  useEffect(() => undo.current?.focus(), []);
  return (
    <div className="work-trashed">
      <div className="work-trashed-line">
        <p role="status">{t.contactArchived}</p>
        <button
          ref={undo}
          type="button"
          className="sk-btn--secondary sk-btn--compact"
          disabled={busy}
          onClick={onRestore}
        >
          {t.undo}
        </button>
      </div>
      <p className="work-trashed-where">{t.archivedReadOnly}</p>
    </div>
  );
}
