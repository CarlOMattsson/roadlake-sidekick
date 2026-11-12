import { appLocale } from "../../mcp-apps/app-locale";
import { roomEnabled } from "../../mcp-apps/enabled-rooms";
import { controlEntry } from "../../mcp-apps/ui/control-entry";
import type { WorkLabels } from "../shared/labels";

/**
 * What the Task view shows after a delete: the Task is in the trash, Ångra takes it back, and where the trash is.
 * A failed Ångra says so and the same button tries again (it reuses its idempotency key).
 */
export function TaskTrashed({
  labels: t,
  busy,
  failed,
  onRestore,
}: {
  labels: WorkLabels;
  busy: boolean;
  /** The last Ångra did not go through. */
  failed: boolean;
  onRestore: () => void;
}) {
  return (
    <div className="work-trashed">
      <div className="work-trashed-line">
        <p role="status">{t.taskTrashed}</p>
        <button
          type="button"
          className="sk-btn--secondary sk-btn--compact"
          disabled={busy}
          onClick={onRestore}
        >
          {t.undo}
        </button>
      </div>
      {roomEnabled("control") && (
        <p className="work-trashed-where">
          {t.taskTrashedWhere(controlEntry(appLocale()).label)}
        </p>
      )}
      {failed && <p role="alert">{t.taskRestoreFailed}</p>}
    </div>
  );
}
