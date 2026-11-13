import { useCallback, useRef, useState } from "react";
import { useSingleFlight } from "../shared/use-single-flight";
import { useLinkUndo } from "../tasks/task-contacts";
import {
  journalEntriesOf,
  type WorkContactAlias,
  type WorkContactChanges,
  type WorkContactContext,
  type WorkContactRecord,
  type WorkJournalEntries,
  type WorkProjectSummary,
  type WorkTaskSummary,
  type WorkTransport,
} from "../transport/transport";
import type { MorePhase } from "../view/parts/frame-types";
import { useFrameRead, type DetailFrame } from "../view/parts/use-detail-frame";

/**
 * What the Contact frame holds besides the shared detail-frame state: the Contact with its Projects, Tasks
 * and linked Journal entries, the "Show more" page of Tasks, and every Contact write (edit, tags, nickname,
 * archive, unlinking a Project). The frame draws it; this hook reads and writes.
 */
export function useContactRecord({
  id,
  transport,
  frame,
  refreshKey,
}: {
  id: string;
  transport: WorkTransport;
  frame: DetailFrame;
  refreshKey: number;
}) {
  const [contact, setContact] = useState<WorkContactRecord>();
  // The Projects come with the context and are shown as read: only the first page is requested.
  const [projects, setProjects] = useState<WorkProjectSummary[]>([]);
  const [tasks, setTasks] = useState<WorkTaskSummary[]>([]);
  // The newest linked Journal entries; read from the context, shown only when the host can open one.
  const [journal, setJournal] = useState<WorkJournalEntries>();
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [more, setMore] = useState<MorePhase>("idle");
  // Set once Archive in this view has written: the page then shows its receipt with Undo until the Contact is restored.
  const [archivedHere, setArchivedHere] = useState(false);
  // Runs the last failed write again; the same action keeps its key, so the server replays it.
  const retryWrite = useRef<(() => void) | undefined>(undefined);
  // "Ta bort koppling till {projekt}" in the ⋯: the Project row stays with its Ångra until the view is read again.
  const unlinks = useLinkUndo((projectId, link, key) =>
    link
      ? transport.linkContactToProject(id, projectId, key)
      : transport.unlinkContactFromProject(id, projectId, key),
  );

  // One "Show more" page per read generation, claimed before React re-renders the button.
  const pages = useSingleFlight();
  function loadMore() {
    const current = frame.ticket.current;
    if (!nextCursor || !pages.enter(current)) return;
    setMore("busy");
    transport
      .getContactContext(id, nextCursor)
      .then((result) => {
        if (current !== frame.ticket.current) return;
        setTasks((known) => [...known, ...result.tasks.items]);
        setNextCursor(result.tasks.next_cursor);
        setMore("idle");
      })
      .catch(() => {
        if (current === frame.ticket.current) setMore("failed");
      })
      .finally(() => pages.leave(current));
  }
  /** Stores a read context: the Contact, its Projects, the first page of Tasks and the Journal entries. */
  function applyContext(result: WorkContactContext) {
    setContact(result.contact);
    setProjects(result.projects.items);
    setTasks(result.tasks.items);
    setNextCursor(result.tasks.next_cursor);
    setJournal(journalEntriesOf(result.journal_entries));
  }
  useFrameRead(
    frame,
    useCallback(() => transport.getContactContext(id), [transport, id]),
    applyContext,
    refreshKey,
  );
  function retry() {
    setMore("idle");
    frame.retry();
  }
  /**
   * One Contact write. The signature names the action and the version it was based on, so a retry
   * of the same action reuses its key and any other action gets a fresh one. `receipt`: the page draws its own receipt
   * for this write, so no plain "Sparat" stands beside it.
   */
  function runWrite(
    signature: string,
    action: "save" | "write",
    send: (key: string) => Promise<{ contact: WorkContactRecord }>,
    done?: () => void,
    receipt = false,
  ) {
    if (!contact || frame.flight.isRunning()) return;
    retryWrite.current = () => runWrite(signature, action, send, done, receipt);
    frame.sendWrite(
      signature,
      action,
      send,
      (result) => {
        retryWrite.current = undefined;
        // A "Show more" page still on its way was dropped with the read: its busy state is cleared here.
        setMore("idle");
        setContact(result.contact);
        done?.();
      },
      receipt,
    );
  }
  function leaveEditor() {
    frame.setEditing(false);
    frame.heading.current?.focus();
  }
  /** Writes only the changed fields against the version the view holds; the key follows the action. */
  function saveContact(changes: WorkContactChanges) {
    if (!contact || frame.flight.isRunning()) return;
    if (Object.keys(changes).length === 0) {
      frame.stopEdit();
      return;
    }
    runWrite(
      JSON.stringify(["update", contact.id, contact.version, changes]),
      "save",
      (key) =>
        transport.updateContact(contact.id, contact.version, changes, key),
      leaveEditor,
    );
  }
  /** Writes the Contact's whole tag set (update_contact changes.tags); `done` runs once it is stored. */
  function setTags(tags: string[], done: () => void) {
    if (!contact) return;
    runWrite(
      JSON.stringify(["tags", contact.id, contact.version, tags]),
      "write",
      (key) =>
        transport.updateContact(contact.id, contact.version, { tags }, key),
      done,
    );
  }
  function addAlias(value: string, done: () => void) {
    if (!contact) return;
    runWrite(
      JSON.stringify(["alias-add", contact.id, contact.version, value]),
      "write",
      (key) =>
        transport.addContactAlias(contact.id, contact.version, value, key),
      done,
    );
  }
  function removeAlias(alias: WorkContactAlias) {
    if (!contact) return;
    runWrite(
      JSON.stringify(["alias-remove", contact.id, contact.version, alias.id]),
      "write",
      (key) =>
        transport.removeContactAlias(
          contact.id,
          alias.id,
          contact.version,
          key,
        ),
    );
  }
  /** Archive and Restore write at once (no question first): Restore undoes Archive, so the receipt carries Undo. */
  function setArchived(archive: boolean) {
    if (!contact) return;
    runWrite(
      JSON.stringify([
        archive ? "archive" : "restore",
        contact.id,
        contact.version,
      ]),
      "write",
      (key) =>
        archive
          ? transport.archiveContact(contact.id, contact.version, key)
          : transport.restoreContact(contact.id, contact.version, key),
      () => {
        setArchivedHere(archive);
        leaveEditor();
      },
      // Archive is answered by its receipt ("Kontakten är arkiverad" with Ångra); Restore has none.
      archive,
    );
  }
  /** Fetches the latest Contact and its first page of Tasks; the open editor keeps the typed values. */
  function reloadContact() {
    frame.reload(
      () => transport.getContactContext(id),
      (result) => {
        applyContext(result);
        setMore("idle");
      },
      () => {
        retryWrite.current = undefined;
      },
    );
  }
  return {
    contact,
    projects,
    tasks,
    journal,
    nextCursor,
    more,
    archivedHere,
    unlinks,
    loadMore,
    retry,
    saveContact,
    setTags,
    addAlias,
    removeAlias,
    setArchived,
    reloadContact,
    retryLastWrite: () => retryWrite.current?.(),
  };
}

export type ContactRecord = ReturnType<typeof useContactRecord>;
