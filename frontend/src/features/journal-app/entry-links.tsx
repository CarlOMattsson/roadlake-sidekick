import { useEffect, useRef, useState } from "react";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { linkName } from "./entry-card";
import { KeyScope } from "../mcp-apps/ui/key-scope";
import type { JournalLabels } from "./labels";
import {
  writeFailure,
  type JournalEntry,
  type JournalEntryLink,
  type JournalTransport,
} from "./transport";
import "./journal.css";

/** The same link, by kind and id: a chip and the link asked about are the same link. */
function sameLink(a: JournalEntryLink, b: JournalEntryLink): boolean {
  return a.kind === b.kind && a.id === b.id;
}

/** The link removed last, with the entry it was removed from, so an Undo never follows another entry. */
type Removed = { entryId: string; link: JournalEntryLink };

/** The link writes that can fail: a removal, the Undo of a removal, or a version conflict. */
type Failure = "remove" | "restore" | "conflict";

/**
 * The linked Projects and Contacts of one entry as chips, in the entry's fullscreen view. A contact's name
 * opens the contact when the host passes `onOpenContact`. While the entry is being changed (`removable`), each chip has
 * a remove button (when the transport can write links) that first asks, then removes the link at the entry's version and offers Undo for it.
 * The parent owns the entry: `onChanged` hands it the answer (new version and links), which it passes back as
 * `entry`. Nothing renders when the entry has no links and there is nothing to undo or report.
 */
export function EntryLinks({
  entry,
  labels: t,
  transport,
  onOpenContact,
  onChanged,
  onConflict,
  removable = true,
}: {
  entry: JournalEntry;
  labels: JournalLabels;
  transport: JournalTransport;
  onOpenContact?: (link: { id: string; label: string | null }) => void;
  onChanged: (entry: JournalEntry) => void;
  /** Runs when the write was refused for a stale version; the parent reads the entry again. */
  onConflict: () => void;
  /**
   * Whether the chips carry their ×. The entry passes true only while it is being changed (its edit mode), so a tap meant to
   * open a Contact never lands on its remove button.
   */
  removable?: boolean;
}) {
  const links = entry.links ?? [];
  const canWrite = transport.updateEntryLinks !== undefined && removable;
  // With the Contact room off, a contact name is plain text and its link cannot be changed here.
  const contactsOn = roomEnabled("contacts");
  // The link the user is asked about: removing a link takes a second step.
  const [asking, setAsking] = useState<JournalEntryLink | undefined>();
  // The link asked about last: its remove button gets focus back when the question closes without a removal.
  const [lastAsked, setLastAsked] = useState<JournalEntryLink | undefined>();
  const [removed, setRemoved] = useState<Removed | undefined>();
  const [failure, setFailure] = useState<Failure | undefined>();
  const [busy, setBusy] = useState(false);
  // The key of the write in flight or the last failed one: a retry of the same write reuses it.
  const pendingKey = useRef<PendingKey | undefined>(undefined);
  // Where focus goes after the question opens or closes: its `linkRemoveConfirm` when it opens, the chip's × when it
  // closes, and the list itself after a removal (the chip is gone by then).
  const focusNext = useRef<"confirm" | "chip" | "list" | undefined>(undefined);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const chipRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const target = focusNext.current;
    if (!target) return;
    focusNext.current = undefined;
    if (target === "confirm") confirmRef.current?.focus();
    else if (target === "chip") (chipRef.current ?? listRef.current)?.focus();
    else listRef.current?.focus();
  }, [asking]);

  function askRemoval(link: JournalEntryLink) {
    focusNext.current = "confirm";
    setLastAsked(link);
    setAsking(link);
  }

  function closeAsk(target: "chip" | "list") {
    focusNext.current = target;
    setAsking(undefined);
  }

  /** Removes the link, or adds it back (Undo), at the entry's current version. */
  function changeLink(action: "remove" | "restore", link: JournalEntryLink) {
    const write = transport.updateEntryLinks;
    if (!write || busy) return;
    const signature = JSON.stringify([
      action,
      entry.id,
      entry.version,
      link.kind,
      link.id,
    ]);
    const pending = keyFor(pendingKey.current, signature);
    pendingKey.current = pending;
    setBusy(true);
    setFailure(undefined);
    if (action === "remove") setRemoved(undefined);
    const field =
      `${action === "remove" ? "remove" : "add"}_${link.kind}_ids` as const;
    write(entry.id, entry.version, { [field]: [link.id] }, pending.key)
      .then((result) => {
        pendingKey.current = undefined;
        setRemoved(
          action === "remove" ? { entryId: entry.id, link } : undefined,
        );
        onChanged(result.entry);
      })
      .catch((error: unknown) => {
        const conflict = writeFailure(error) === "conflict";
        setFailure(
          conflict ? "conflict" : action === "remove" ? "remove" : "restore",
        );
        if (conflict) onConflict();
      })
      .finally(() => setBusy(false));
  }

  const undoable =
    removed && removed.entryId === entry.id ? removed : undefined;
  if (links.length === 0 && !undoable && !failure && !asking) return null;

  return (
    <div
      className="journal-entry-links"
      role="group"
      aria-label={t.linked}
      ref={listRef}
      tabIndex={-1}
    >
      {asking ? (
        <KeyScope
          className="journal-undo journal-link-ask"
          role="group"
          onEscape={() => closeAsk("chip")}
        >
          <p role="status">{t.linkRemoveAsk(linkName(asking, t))}</p>
          <button
            ref={confirmRef}
            type="button"
            className="sk-btn--primary"
            disabled={busy}
            onClick={() => {
              const link = asking;
              closeAsk("list");
              changeLink("remove", link);
            }}
          >
            {t.linkRemoveConfirm}
          </button>
          <button
            type="button"
            className="sk-btn--quiet"
            onClick={() => closeAsk("chip")}
          >
            {t.cancel}
          </button>
        </KeyScope>
      ) : (
        <>
          {links.length > 0 && (
            <ul className="journal-chips">
              {links.map((link) => {
                const name = linkName(link, t);
                return (
                  <li key={`${link.kind}:${link.id}`} className="journal-chip">
                    {contactsOn && onOpenContact && link.kind === "contact" ? (
                      <button
                        type="button"
                        className="journal-chip-name"
                        title={name}
                        onClick={() =>
                          onOpenContact({ id: link.id, label: link.label })
                        }
                      >
                        {name}
                      </button>
                    ) : (
                      <span className="journal-chip-name" title={name}>
                        {name}
                      </span>
                    )}
                    {canWrite && (contactsOn || link.kind !== "contact") && (
                      <button
                        ref={
                          lastAsked && sameLink(lastAsked, link)
                            ? chipRef
                            : undefined
                        }
                        type="button"
                        className="sk-btn--quiet journal-chip-remove"
                        aria-label={t.linkRemove(name)}
                        disabled={busy}
                        onClick={() => askRemoval(link)}
                      >
                        ×
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {undoable && (
            <div className="journal-undo">
              <p role="status">{t.linkRemoved(linkName(undoable.link, t))}</p>
              <button
                type="button"
                className="sk-btn--quiet"
                onClick={() => changeLink("restore", undoable.link)}
                disabled={busy}
              >
                {t.undo}
              </button>
            </div>
          )}
          {failure && (
            <ErrorNotice
              placement="row"
              locale={t.dateLocale}
              message={
                failure === "conflict"
                  ? t.entryReloadedConflict
                  : failure === "remove"
                    ? t.linkRemoveFailed
                    : t.linkRestoreFailed
              }
            />
          )}
        </>
      )}
    </div>
  );
}
