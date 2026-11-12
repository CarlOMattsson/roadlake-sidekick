import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import {
  ContactSummary,
  ContactsSummary,
  InlineSummary,
  type ContactLinkCounts,
  type InlineSummaryData,
  type InlineSummaryNotice,
} from "../inline-summary";
import type { InlineSummaryLabels } from "../inline-summary-labels";
import {
  writeFailure,
  type WorkContactRecord,
  type WorkContactsFrame,
  type WorkTransport,
} from "../transport";
import { readFailurePhase, type Phase } from "./frame-types";
import {
  contactLinkCounts,
  contactNames,
  projectInlineSummary,
  taskInlineSummary,
} from "./inline-data";
import { useMounted } from "./use-mounted";

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
  const [notice, setNotice] = useState<InlineSummaryNotice>();
  // One key per attempt: a retry of the same write against the same version reuses it.
  const pendingDone = useRef<PendingKey | undefined>(undefined);
  const alive = useMounted();
  const [phase, setPhase] = useState<Phase>(initial ? "ready" : "loading");
  const [summary, setSummary] = useState<InlineSummaryData | undefined>(
    initial,
  );
  const [attempt, setAttempt] = useState(0);
  // Whether the tool result carried the record: it only decides the first read, so it is fixed at mount.
  const [carried] = useState(initial !== undefined);
  useEffect(() => {
    // The carried record is the first view; only a refresh (attempt > 0) reads it again.
    if (carried && attempt === 0) return;
    // A response from a superseded read or an unmounted summary must not update state.
    let live = true;
    const read: Promise<InlineSummaryData> =
      kind === "task"
        ? transport.getTask(id).then(({ task }) => taskInlineSummary(task))
        : transport
            .getProject(id)
            .then(({ project }) => projectInlineSummary(project));
    read
      .then((next) => {
        if (!live) return;
        setSummary(next);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (live) setPhase(readFailurePhase(error));
      });
    return () => {
      live = false;
    };
  }, [transport, kind, id, attempt, carried]);
  function reload() {
    pendingDone.current = undefined;
    setNotice(undefined);
    setPhase("loading");
    setAttempt((n) => n + 1);
  }
  /**
   * Marks the Task done with update_task against the version the summary shows, so no get_task
   * comes first. A conflict offers "Read again"; a network failure offers a retry that reuses the
   * same idempotency key. The host model hears about a saved change through `announce`.
   */
  async function complete() {
    if (busy || summary?.version === undefined) return;
    const { version } = summary;
    setBusy(true);
    setNotice(undefined);
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
      announce?.(labels.completedNote);
    } catch (error) {
      if (!alive.current) return;
      const failure = writeFailure(error);
      if (failure === "conflict") {
        pendingDone.current = undefined;
        setNotice({
          message: labels.conflict,
          actionLabel: labels.reread,
          action: reload,
        });
      } else if (failure === "failed") {
        setNotice({
          message: labels.saveFailed,
          actionLabel: labels.retry,
          action: () => void complete(),
        });
      } else if (failure === "not_found") {
        pendingDone.current = undefined;
        setNotice({ message: labels.notFound });
      } else {
        pendingDone.current = undefined;
        setNotice({ message: labels.saveFailed });
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }
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
        notice={notice}
      />
    );
  }
  return <InlineSummary state="loading" labels={labels} />;
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
  const [counts, setCounts] = useState<ContactLinkCounts>();
  // Set when the read says the Contact no longer exists: the card then shows only that line.
  const [gone, setGone] = useState(false);
  useEffect(() => {
    // A response from an unmounted card must not update state.
    let live = true;
    transport
      .getContactContext(contact.id)
      .then((context) => {
        if (live) setCounts(contactLinkCounts(context));
      })
      .catch((error: unknown) => {
        // The counts are optional; the card still shows the Contact and Open, unless it is gone.
        if (live && writeFailure(error) === "not_found") setGone(true);
      });
    return () => {
      live = false;
    };
  }, [transport, contact.id]);
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
  const [phase, setPhase] = useState<Phase>(frame.page ? "ready" : "loading");
  const [matches, setMatches] = useState(() => ({
    count: frame.page?.items.length ?? 0,
    more: frame.page ? frame.page.next_cursor !== null : false,
    contacts: contactNames(frame.page?.items ?? []),
  }));
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // A frame that already holds its page needs no read; a retry reads the first page again.
    if (frame.page && attempt === 0) return;
    // A response from an unmounted summary must not update state.
    let live = true;
    transport
      .listContacts({
        q: frame.q.trim(),
        includeArchived: frame.includeArchived,
      })
      .then((next) => {
        if (!live) return;
        setMatches({
          count: next.items.length,
          more: next.next_cursor !== null,
          contacts: contactNames(next.items),
        });
        setPhase("ready");
      })
      .catch(() => {
        if (live) setPhase("error");
      });
    return () => {
      live = false;
    };
  }, [transport, frame, attempt]);
  function reload() {
    setPhase("loading");
    setAttempt((n) => n + 1);
  }
  if (phase === "error") {
    return (
      <InlineSummary
        state="error"
        labels={labels}
        kindLabel={labels.kind.contacts}
        onRetry={reload}
      />
    );
  }
  if (phase === "ready") {
    return (
      <ContactsSummary
        count={matches.count}
        more={matches.more}
        contacts={matches.contacts}
        query={frame.q}
        labels={labels}
        onOpen={onOpen}
      />
    );
  }
  return <InlineSummary state="loading" labels={labels} />;
}
