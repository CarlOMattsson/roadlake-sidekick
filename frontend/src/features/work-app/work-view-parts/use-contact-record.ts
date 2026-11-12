import { useCallback, useRef, useState } from "react";
import { useLinkUndo } from "../task-contacts";
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
} from "../transport";
import type { MorePhase } from "./frame-types";
import { useFrameRead, type DetailFrame } from "./use-detail-frame";

/**
 * What the Contact frame holds besides the shared detail-frame state: the Contact with its Projects, Tasks
 * and linked Journal entries, the "Show more" page of Tasks, and every Contact write (edit, nickname,
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
  // Runs the last failed write again; the same action keeps its key, so the server replays it.
  const retryWrite = useRef<(() => void) | undefined>(undefined);
  // "Ta bort koppling till {projekt}" in the ⋯: the Project row stays with its Ångra until the view is read again.
  const unlinks = useLinkUndo((projectId, link, key) =>
    link
      ? transport.linkContactToProject(id, projectId, key)
      : transport.unlinkContactFromProject(id, projectId, key),
  );

  function loadMore() {
    if (!nextCursor || more === "busy") return;
    const current = frame.ticket.current;
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
      });
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
   * of the same action reuses its key and any other action gets a fresh one.
   */
  function runWrite(
    signature: string,
    action: "save" | "write",
    send: (key: string) => Promise<{ contact: WorkContactRecord }>,
    done?: () => void,
  ) {
    if (!contact || frame.writing.current) return;
    retryWrite.current = () => runWrite(signature, action, send, done);
    frame.sendWrite(signature, action, send, (result) => {
      retryWrite.current = undefined;
      // A "Show more" page still on its way was dropped with the read: its busy state is cleared here.
      setMore("idle");
      setContact(result.contact);
      done?.();
    });
  }
  function leaveEditor() {
    frame.setEditing(false);
    frame.heading.current?.focus();
  }
  /** Writes only the changed fields against the version the view holds; the key follows the action. */
  function saveContact(changes: WorkContactChanges) {
    if (!contact || frame.writing.current) return;
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
      leaveEditor,
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
    unlinks,
    loadMore,
    retry,
    saveContact,
    addAlias,
    removeAlias,
    setArchived,
    reloadContact,
    retryLastWrite: () => retryWrite.current?.(),
  };
}

export type ContactRecord = ReturnType<typeof useContactRecord>;
