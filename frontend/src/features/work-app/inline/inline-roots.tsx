import { useCallback, useMemo, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import {
  ContactSummary,
  type ContactLinkCounts,
} from "./inline-contact-summary";
import {
  ContactsSummary,
  InlineSummary,
  type InlineSummaryData,
  type InlineSummaryNotice,
} from "./inline-summary";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import { isRecurringCycle, sameDue } from "../agenda/parts/agenda-helpers";
import {
  isTaskStatus,
  writeFailure,
  type WorkContactRecord,
  type WorkContactsFrame,
  type WorkTask,
  type WorkTaskChanges,
  type WorkTransport,
} from "../transport/transport";
import { useSingleFlight } from "../shared/use-single-flight";
import { readFailurePhase, type Phase } from "../view/parts/frame-types";
import {
  contactLinkCounts,
  contactMatches,
  projectInlineSummary,
  taskInlineSummary,
} from "./inline-data";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import { useRead } from "../../mcp-apps/ui/use-read";

/** What Undo after Done writes back: the status the Task had, or for a recurring Task its due date and completion. */
type DoneUndo = {
  changes: WorkTaskChanges;
  /** The Task version Done left; Undo is written against it. */
  version: number;
  /** The reply must show this status, or this due instant, or Undo did not take. */
  restored: { status: string } | { due: string | null };
};

/**
 * The inline root of a Task or Project, shown while fullscreen is offered: it reads the record
 * (get_task or get_project) and shows InlineSummary. "Open" only asks the host for fullscreen; the
 * full view appears when the host switches, through WorkView's fullscreen prop, with no restart.
 */
export function InlineRootSummary({
  kind,
  id,
  initial,
  transport,
  labels,
  onOpen,
  announce,
}: {
  kind: "task" | "project";
  id: string;
  /** The record the tool result carried; shown at once, so no read runs until "Refresh". */
  initial?: InlineSummaryData;
  transport: WorkTransport;
  labels: InlineSummaryLabels;
  onOpen: () => void;
  /** Receives a short sentence for the host model after the Task is marked done. */
  announce?: (summary: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  // Done and Undo share one flight: a second press before the card re-renders does not start a second write.
  const flight = useSingleFlight();
  const [notice, setNotice] = useState<InlineSummaryNotice>();
  // One key per attempt: a retry of the same write against the same version reuses it.
  const pendingDone = useRef<PendingKey | undefined>(undefined);
  const pendingUndo = useRef<PendingKey | undefined>(undefined);
  // Set by Done for `UNDO_MS`: "Done · Undo" stands in the card where Done stood.
  const [undo, setUndo] = useState<DoneUndo>();
  // Undo has run: focus goes to Done, which comes back in place of the Undo that had it.
  const [focusDone, setFocusDone] = useState(false);
  const alive = useMounted();
  // The carried record is the first view; only a refresh reads it again.
  const readSummary = useCallback(
    (): Promise<InlineSummaryData> =>
      kind === "task"
        ? transport.getTask(id).then(({ task }) => taskInlineSummary(task))
        : transport
            .getProject(id)
            .then(({ project }) => projectInlineSummary(project)),
    [transport, kind, id],
  );
  const [read, retryRead, setSummary] = useRead(readSummary, 0, initial);
  const summary = read.phase === "ready" ? read.value : undefined;
  const phase: Phase =
    read.phase === "failed"
      ? readFailurePhase(read.cause)
      : read.phase === "ready"
        ? "ready"
        : "loading";
  function reload() {
    pendingDone.current = undefined;
    pendingUndo.current = undefined;
    setUndo(undefined);
    setNotice(undefined);
    retryRead();
  }
  /**
   * The notice for a failed write: a conflict offers "Read again"; a network failure offers a retry that
   * reuses the same idempotency key (`pending` keeps it); anything else is said once.
   */
  function showFailure(
    error: unknown,
    pending: { current: PendingKey | undefined },
    failedText: string,
    retry: () => void,
  ) {
    const failure = writeFailure(error);
    if (failure === "conflict") {
      pending.current = undefined;
      setNotice({
        message: labels.conflict,
        actionLabel: labels.reread,
        action: reload,
      });
    } else if (failure === "failed") {
      setNotice({
        message: failedText,
        actionLabel: labels.retry,
        action: retry,
      });
    } else if (failure === "not_found") {
      pending.current = undefined;
      setNotice({ message: labels.notFound });
    } else {
      pending.current = undefined;
      setNotice({ message: failedText });
    }
  }
  /**
   * Marks the Task done with update_task against the version the summary shows, so no get_task
   * comes first. The host model hears about a saved change through `announce`, and the card offers
   * Undo for `UNDO_MS` (see `undoDone`).
   */
  async function complete() {
    if (summary?.version === undefined || !flight.enter()) return;
    const { version } = summary;
    setBusy(true);
    setNotice(undefined);
    setFocusDone(false);
    try {
      const signature = JSON.stringify([id, version, "completed"]);
      const pendingKey = keyFor(pendingDone.current, signature);
      pendingDone.current = pendingKey;
      const { task } = await transport.updateTask(
        id,
        version,
        { status: "completed" },
        pendingKey.key,
      );
      pendingDone.current = undefined;
      if (!alive.current) return;
      setSummary(taskInlineSummary(task));
      setUndo(doneUndo(summary, task));
      pendingUndo.current = undefined;
      announce?.(labels.completedNote);
    } catch (error) {
      if (alive.current)
        showFailure(
          error,
          pendingDone,
          labels.doneFailed,
          () => void complete(),
        );
    } finally {
      flight.leave();
      if (alive.current) setBusy(false);
    }
  }
  /**
   * Undo after Done: the earlier status (for a recurring Task its due date and completion) written against
   * the version Done left, with a key of its own. A reply that does not show the restored value is a
   * failure with "Try again", never a card that says it is undone.
   */
  async function undoDone(entry: DoneUndo) {
    if (!flight.enter()) return;
    setBusy(true);
    setNotice(undefined);
    try {
      const signature = JSON.stringify([id, entry.version, entry.changes]);
      const pendingKey = keyFor(pendingUndo.current, signature);
      pendingUndo.current = pendingKey;
      const { task } = await transport.updateTask(
        id,
        entry.version,
        entry.changes,
        pendingKey.key,
      );
      pendingUndo.current = undefined;
      const restored =
        "status" in entry.restored
          ? task.status === entry.restored.status
          : sameDue(task.due_at, entry.restored.due);
      if (!restored) throw new Error("undo not applied");
      if (!alive.current) return;
      setSummary(taskInlineSummary(task));
      setUndo(undefined);
      setFocusDone(true);
      announce?.(labels.undoneNote);
    } catch (error) {
      if (alive.current)
        showFailure(
          error,
          pendingUndo,
          labels.undoFailed,
          () => void undoDone(entry),
        );
    } finally {
      flight.leave();
      if (alive.current) setBusy(false);
    }
  }
  const expireUndo = useCallback(() => setUndo(undefined), []);
  if (phase === "gone") {
    return (
      <InlineSummary
        state="gone"
        labels={labels}
        kindLabel={labels.kind[kind]}
        goneKey={kind === "task" ? "goneTask" : "goneProject"}
      />
    );
  }
  if (phase === "error") {
    return (
      <InlineSummary
        state="error"
        labels={labels}
        kindLabel={labels.kind[kind]}
        subject={`work:${kind}`}
        cause={read.phase === "failed" ? read.cause : undefined}
        onRetry={reload}
      />
    );
  }
  if (phase === "ready" && summary) {
    const canComplete =
      kind === "task" &&
      summary.status !== "completed" &&
      summary.version !== undefined;
    return (
      <InlineSummary
        state="ready"
        labels={labels}
        summary={summary}
        onOpen={onOpen}
        onComplete={canComplete ? () => void complete() : undefined}
        busy={busy}
        undo={
          undo
            ? {
                onUndo: () => void undoDone(undo),
                onExpire: expireUndo,
                busy,
              }
            : undefined
        }
        focusComplete={focusDone}
        notice={notice}
      />
    );
  }
  return <InlineSummary state="loading" labels={labels} />;
}

/**
 * What Undo writes after `task` came back from Done on `before`: the status the Task had; for a recurring
 * Task the server recorded the cycle and reopened it, so its due date and completion are written back. A
 * Task whose earlier status is not one this view writes gets no Undo.
 */
function doneUndo(
  before: InlineSummaryData,
  task: WorkTask,
): DoneUndo | undefined {
  const due = before.dueDate ?? null;
  if (isRecurringCycle(task, due)) {
    return {
      changes: {
        due_at: due,
        last_completed_at: before.lastCompletedAt ?? null,
      },
      version: task.version,
      restored: { due },
    };
  }
  if (!isTaskStatus(before.status)) return undefined;
  return {
    changes: { status: before.status },
    version: task.version,
    restored: { status: before.status },
  };
}

/**
 * The inline root of a Contact, shown while fullscreen is offered: the tool result already holds the
 * Contact, and get_contact_context adds how many Projects and Tasks it is linked to. A read that
 * fails leaves the counts out. "Open" only asks the host for fullscreen; the Contact view with its
 * editor appears there, through WorkView's fullscreen prop.
 */
export function InlineContactRoot({
  contact,
  transport,
  kindLabel,
  labels,
  onOpen,
}: {
  contact: WorkContactRecord;
  transport: WorkTransport;
  kindLabel: string;
  labels: InlineSummaryLabels;
  onOpen: () => void;
}) {
  // The counts are optional; the card still shows the Contact and Open, unless it is gone.
  const readContext = useCallback(
    () => transport.getContactContext(contact.id).then(contactLinkCounts),
    [transport, contact.id],
  );
  const [read] = useRead(readContext);
  const counts: ContactLinkCounts | undefined =
    read.phase === "ready" ? read.value : undefined;
  // Set when the read says the Contact no longer exists: the card then shows only that line.
  const gone =
    read.phase === "failed" && writeFailure(read.cause) === "not_found";
  if (gone) {
    return (
      <InlineSummary
        state="gone"
        labels={labels}
        kindLabel={kindLabel}
        goneKey="goneContact"
      />
    );
  }
  return (
    <ContactSummary
      kindLabel={kindLabel}
      name={contact.display_name}
      email={contact.email}
      relationship={contact.relationship}
      organization={contact.organization}
      role={contact.role}
      tags={contact.tags}
      aliases={contact.aliases.map((nickname) => nickname.value)}
      counts={counts}
      labels={labels}
      onOpen={onOpen}
    />
  );
}

/**
 * The inline root of the Contact list, shown while fullscreen is offered: it counts the matches on
 * the page the frame holds, or reads the first page when the frame holds none. "Open" only asks the
 * host for fullscreen; the list appears when the host switches, through WorkView's fullscreen prop.
 */
export function ContactsRootSummary({
  frame,
  transport,
  labels,
  onOpen,
}: {
  frame: WorkContactsFrame;
  transport: WorkTransport;
  labels: InlineSummaryLabels;
  onOpen: () => void;
}) {
  // A frame that already holds its page needs no read; a retry reads the first page again.
  const held = useMemo(
    () => (frame.page ? contactMatches(frame.page) : undefined),
    [frame.page],
  );
  const readMatches = useCallback(
    () =>
      transport
        .listContacts({
          q: frame.q.trim(),
          includeArchived: frame.includeArchived,
        })
        .then(contactMatches),
    [transport, frame],
  );
  const [read, reload] = useRead(readMatches, 0, held);
  if (read.phase === "failed") {
    return (
      <InlineSummary
        state="error"
        labels={labels}
        kindLabel={labels.kind.contacts}
        subject="contacts"
        cause={read.cause}
        onRetry={reload}
      />
    );
  }
  if (read.phase === "ready") {
    return (
      <ContactsSummary
        count={read.value.count}
        more={read.value.more}
        contacts={read.value.contacts}
        query={frame.q}
        labels={labels}
        onOpen={onOpen}
      />
    );
  }
  return <InlineSummary state="loading" labels={labels} />;
}
