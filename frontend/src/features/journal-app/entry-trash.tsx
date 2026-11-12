import { useId, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { appLocale } from "../mcp-apps/app-locale";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import {
  BackHeaderActions,
  useBackHeaderSlot,
} from "../mcp-apps/ui/back-header";
import { MoreIcon } from "../mcp-apps/ui/icons";
import { controlEntry } from "../mcp-apps/ui/control-entry";
import type { JournalLabels } from "./labels";
import {
  writeFailure,
  type JournalEntry,
  type JournalTransport,
  type WriteFailure,
} from "./transport";
import "./journal.css";

/** What the entry view knows about a deletion: nothing yet, one under way, or one that went to the trash. */
export type EntryTrash = {
  /** The trash record's version when the entry is in the trash; Undo needs it. Absent: the entry is not deleted. */
  trashed?: { version: number };
  busy: boolean;
  /** How the last delete or Undo failed. Cleared by the next try. */
  failure?: { action: "trash" | "restore"; how: WriteFailure };
  /** Moves the entry to the trash. The same entry and version reuse the idempotency key, so a retry cannot delete twice. */
  trash: () => void;
  /** Takes the entry back out of the trash; `restored` runs after the server has done it. */
  restore: (restored: () => void) => void;
};

/**
 * The delete-with-Undo of one entry: move_to_trash at the entry's version, restore_from_trash at the trash
 * version it answered with. No question first, because the trash and Undo make it reversible (the same rule
 * as the other rooms). `onConflict` runs when the version was stale; the parent reads the entry again.
 */
export function useEntryTrash(
  transport: JournalTransport,
  entry: JournalEntry | undefined,
  onConflict: () => void,
): EntryTrash {
  const [trashed, setTrashed] = useState<{ version: number }>();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<EntryTrash["failure"]>();
  const pendingKey = useRef<PendingKey | undefined>(undefined);

  function trash() {
    const write = transport.trashEntry;
    if (!write || !entry || busy) return;
    const pending = keyFor(
      pendingKey.current,
      JSON.stringify(["trash", entry.id, entry.version]),
    );
    pendingKey.current = pending;
    setBusy(true);
    setFailure(undefined);
    write(entry.id, entry.version, pending.key)
      .then((result) => {
        pendingKey.current = undefined;
        setTrashed({ version: result.version });
      })
      .catch((error: unknown) => {
        const how = writeFailure(error);
        setFailure({ action: "trash", how });
        if (how === "conflict") onConflict();
      })
      .finally(() => setBusy(false));
  }

  function restore(restored: () => void) {
    const write = transport.restoreEntry;
    if (!write || !entry || !trashed || busy) return;
    const pending = keyFor(
      pendingKey.current,
      JSON.stringify(["restore", entry.id, trashed.version]),
    );
    pendingKey.current = pending;
    setBusy(true);
    setFailure(undefined);
    write(entry.id, trashed.version, pending.key)
      .then(() => {
        pendingKey.current = undefined;
        setTrashed(undefined);
        restored();
      })
      .catch((error: unknown) =>
        setFailure({ action: "restore", how: writeFailure(error) }),
      )
      .finally(() => setBusy(false));
  }

  return { trashed, busy, failure, trash, restore };
}

/**
 * The entry's ⋯ with its one item, "Delete entry". In the shell's Back row the ⋯ sits at the end of the row (pen,
 * then ⋯); with no shell Back it sits on its own row above the date. The menu opens under the heading. Escape
 * closes it and gives the focus back to ⋯.
 */
export function EntryMenu({
  labels: t,
  disabled,
  onTrash,
}: {
  labels: JournalLabels;
  disabled: boolean;
  onTrash: () => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const inShell = useBackHeaderSlot();
  const more = (
    <button
      ref={button}
      type="button"
      className="sk-iconbtn"
      aria-label={t.entryMoreActions}
      aria-expanded={open}
      aria-controls={open ? panelId : undefined}
      disabled={disabled}
      onClick={() => setOpen(!open)}
    >
      <MoreIcon />
    </button>
  );
  return (
    <>
      {inShell ? (
        <BackHeaderActions>{more}</BackHeaderActions>
      ) : (
        <div className="journal-entry-bar">{more}</div>
      )}
      {open && (
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a container-level handler for keys bubbling up from the focusable controls inside it (Escape closes); the container itself is not a control.
        <div
          id={panelId}
          className="journal-more-panel"
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            setOpen(false);
            button.current?.focus();
          }}
        >
          <button
            type="button"
            className="journal-more-item journal-more-item--danger"
            onClick={() => {
              setOpen(false);
              onTrash();
            }}
          >
            {t.deleteEntry}
          </button>
        </div>
      )}
    </>
  );
}

/**
 * What the entry view shows after a delete: the entry is in the trash, Undo takes it back, and where the trash
 * is. A failed Undo says so and the same button tries again.
 */
export function EntryTrashed({
  labels: t,
  state,
  onRestore,
}: {
  labels: JournalLabels;
  state: EntryTrash;
  onRestore: () => void;
}) {
  const failed =
    state.failure?.action === "restore" ? state.failure : undefined;
  return (
    <div className="journal-trashed">
      <div className="journal-undo">
        <p role="status">{t.entryTrashed}</p>
        <button
          type="button"
          className="sk-btn--secondary"
          disabled={state.busy}
          onClick={onRestore}
        >
          {t.undo}
        </button>
      </div>
      {roomEnabled("control") && (
        <p className="journal-muted">
          {t.entryTrashedWhere(controlEntry(appLocale()).label)}
        </p>
      )}
      {failed && (
        <p role="alert" className="journal-banner">
          {failed.how === "forbidden" ? t.forbiddenWrite : t.entryRestoreFailed}
        </p>
      )}
    </div>
  );
}

/** The line under a failed delete, with a retry that reuses the attempt's idempotency key. */
export function EntryTrashFailure({
  labels: t,
  how,
  busy,
  onRetry,
}: {
  labels: JournalLabels;
  how: WriteFailure;
  busy: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="journal-undo">
      <p role="alert" className="journal-banner">
        {how === "forbidden"
          ? t.forbiddenWrite
          : how === "conflict"
            ? t.entryTrashConflict
            : t.entryTrashFailed}
      </p>
      {how !== "forbidden" && (
        <button
          type="button"
          className="sk-btn--secondary"
          disabled={busy}
          onClick={onRetry}
        >
          {t.retry}
        </button>
      )}
    </div>
  );
}
