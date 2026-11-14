import { useEffect, useRef, useState } from "react";
import type { CardLabels } from "../shared/card-labels";
import { knownLabel } from "../shared/labels";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { createSupersession } from "../../mcp-apps/supersede";
import { RecordTitle } from "../board/board-card";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { CardFoot } from "../../mcp-apps/ui/card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { NoticeRow, type InlineSummaryNotice } from "./inline-summary-list";
import {
  TASK_STATUSES,
  writeFailure,
  type TaskStatusValue,
  type WorkCardFrame,
  type WorkFrame,
  type WorkItemRecord,
  type WorkTransport,
} from "../transport/transport";
import { useSingleFlight } from "../shared/use-single-flight";
import { cardKey, frameFor } from "../shared/work-items";

/** Rows the card shows; the rest of the server's list is counted in "+N". */
const MAX_ROWS = 5;

/** BroadcastChannel shared by all copies of a work card, so an older copy learns it was replaced. */
export const WORK_CARD_CHANNEL = "sidekick-work-cards";

/**
 * The two calls a status change needs. The view passes its own transport; the card holds no
 * credential and no backend URL.
 */
export type CardStatusWriter = Pick<WorkTransport, "getTask" | "updateTask">;

/**
 * The inline card. Three states besides the loaded one: loading (skeleton), error (the shared read
 * notice under the app's name, with "Try again" only when a re-read exists) and an empty list. The card has no inner scroll. Its actions are "Open" and
 * "Try again", plus, when a writer is given, a status segment per Task row (update_task). When
 * `onOpenItem` is given (fullscreen), the title of a Task or Project row is a button that opens it.
 */
export type WorkCardProps =
  | { state: "loading"; labels: CardLabels }
  | {
      state: "error";
      labels: CardLabels;
      /** The app's name above the notice (`appName`), not the card's own title. */
      appTitle: string;
      /** Locale of the notice text: the work labels' dateLocale, as elsewhere in Work. */
      locale: string;
      /** The failure, when the caller has it: decides the notice's second line. */
      cause?: unknown;
      /** The notice subject that names what Try again reads ("work", "work:hierarchy", "contacts"). */
      subject: string;
      onRetry?: () => void;
      retrying?: boolean;
    }
  | {
      state: "ready";
      labels: CardLabels;
      frame: WorkCardFrame;
      onOpen?: () => void;
      /** True while the host answers the fullscreen request: Open is busy and cannot be pressed. */
      opening?: boolean;
      /** Text of the Open button while it is busy (WorkLabels.opening). */
      openingLabel?: string;
      /** Opens a row's frame; given only in fullscreen, where the row titles become buttons. */
      onOpenItem?: (frame: WorkFrame) => void;
      /** Enables status segments on Task rows; without it the rows stay read-only. */
      writer?: CardStatusWriter;
      /** Receives a short sentence for the host model after a status change is saved. */
      announce?: (summary: string) => void;
    };

export function WorkCard(props: WorkCardProps) {
  const { labels } = props;

  if (props.state === "loading") {
    return (
      <section className="work-compact-card sk-card" aria-busy="true">
        <p className="sk-eyebrow">{labels.appName}</p>
        <p role="status" className="work-compact-status">
          {labels.loading}
        </p>
        <span className="work-compact-skeleton" aria-hidden="true" />
        <span
          className="work-compact-skeleton work-compact-skeleton-short"
          aria-hidden="true"
        />
      </section>
    );
  }

  if (props.state === "error") {
    return (
      <section className="work-compact-card sk-card">
        <p className="sk-eyebrow">{props.appTitle}</p>
        <ErrorNotice
          locale={props.locale}
          // An error result names no record: the heading names what Try again reads.
          subject={props.subject}
          cause={props.cause}
          onRetry={props.onRetry}
          retrying={props.retrying}
        />
      </section>
    );
  }

  return (
    <ReadyCard
      labels={labels}
      frame={props.frame}
      onOpen={props.onOpen}
      opening={props.opening}
      openingLabel={props.openingLabel}
      onOpenItem={props.onOpenItem}
      writer={props.writer}
      announce={props.announce}
    />
  );
}

/** A row's status as this card last saw or wrote it, after a successful change or a re-read. */
type Override = { status: string; version: number };

function ReadyCard({
  labels,
  frame,
  onOpen,
  opening = false,
  openingLabel,
  onOpenItem,
  writer,
  announce,
}: {
  labels: CardLabels;
  frame: WorkCardFrame;
  onOpen?: () => void;
  opening?: boolean;
  openingLabel?: string;
  onOpenItem?: (frame: WorkFrame) => void;
  writer?: CardStatusWriter;
  announce?: (summary: string) => void;
}) {
  const [seen, setSeen] = useState(frame);
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [busy, setBusy] = useState<string>();
  // A status change and a re-read share one flight: a second press before the card re-renders does not start another.
  const flight = useSingleFlight();
  const [notice, setNotice] = useState<InlineSummaryNotice>();
  // True once a younger copy of this card exists. Read by async code, so it is also a ref.
  const [superseded, setSuperseded] = useState(false);
  const supersededRef = useRef(false);
  // One key per attempt: a retry of the same status change against the same version reuses it.
  const pending = useRef(new Map<string, PendingKey>());
  // A new frame from the host replaces the records, so the local overrides belong to the old one.
  if (frame !== seen) {
    setSeen(frame);
    setOverrides({});
    setNotice(undefined);
  }

  // Joins the copies of this card by server issued_at. Without issued_at the card is never superseded.
  const issuedAt = frame.issuedAt;
  useEffect(() => {
    supersededRef.current = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the supersession starts unset for each issued_at before the channel reports.
    setSuperseded(false);
    if (issuedAt === undefined) return undefined;
    const supersession = createSupersession({
      channel: WORK_CARD_CHANNEL,
      issuedAt,
      onSuperseded: () => {
        supersededRef.current = true;
        setSuperseded(true);
      },
    });
    return () => supersession.dispose();
  }, [issuedAt]);

  const shown = frame.items.slice(0, MAX_ROWS);
  const hidden = Math.max(0, frame.total - shown.length);
  const statusWriter = writer;

  /** The row as this card holds it now: the record as read, or the status it last wrote. */
  function current(item: WorkItemRecord): WorkItemRecord {
    const over = overrides[cardKey(item)];
    return over
      ? { ...item, status: over.status, version: over.version }
      : item;
  }

  /**
   * Writes one status change against the version the row shows (read with get_task when the row
   * has none). A conflict offers "Read again"; a network failure offers a retry with the same key.
   */
  async function change(
    item: WorkItemRecord,
    to: TaskStatusValue,
    w: CardStatusWriter,
  ) {
    if (supersededRef.current || !flight.enter()) return;
    const key = cardKey(item);
    setBusy(key);
    setNotice(undefined);
    try {
      const version =
        current(item).version ?? (await w.getTask(item.id)).task.version;
      const signature = JSON.stringify([item.id, version, to]);
      const pendingKey = keyFor(pending.current.get(key), signature);
      pending.current.set(key, pendingKey);
      const { task } = await w.updateTask(
        item.id,
        version,
        { status: to },
        pendingKey.key,
      );
      pending.current.delete(key);
      setOverrides((all) => ({
        ...all,
        [key]: { status: task.status, version: task.version },
      }));
      // A replaced copy saves but does not tell the host model; only the latest card speaks.
      if (!supersededRef.current) {
        announce?.(
          labels.statusChanged.replace(
            "{status}",
            labels.taskStatus[to].toLocaleLowerCase(),
          ),
        );
      }
    } catch (error) {
      const failure = writeFailure(error);
      if (failure === "conflict") {
        pending.current.delete(key);
        setNotice({
          message: labels.statusConflict,
          actionLabel: labels.reread,
          action: () => void reread(item, w),
        });
      } else if (failure === "failed") {
        setNotice({
          message: labels.statusFailed,
          actionLabel: labels.retry,
          action: () => void change(item, to, w),
        });
      } else if (failure === "not_found") {
        pending.current.delete(key);
        setNotice({ message: labels.notFound });
      } else {
        pending.current.delete(key);
        setNotice({ message: labels.statusFailed });
      }
    } finally {
      flight.leave();
      setBusy(undefined);
    }
  }

  /** Reads the latest Task so the row shows its current status and version. */
  async function reread(item: WorkItemRecord, w: CardStatusWriter) {
    if (!flight.enter()) return;
    const key = cardKey(item);
    setBusy(key);
    setNotice(undefined);
    try {
      const { task } = await w.getTask(item.id);
      setOverrides((all) => ({
        ...all,
        [key]: { status: task.status, version: task.version },
      }));
    } catch {
      setNotice({
        message: labels.statusFailed,
        actionLabel: labels.reread,
        action: () => void reread(item, w),
      });
    } finally {
      flight.leave();
      setBusy(undefined);
    }
  }

  const title = titleFor(labels, frame.total);
  const statusSentence = statusSentenceFor(
    labels,
    frame.total,
    frame.items.map(current),
  );

  return (
    <section className="work-compact-card sk-card" aria-label={title}>
      <p className="sk-eyebrow">{labels.appName}</p>
      <p className="work-compact-title sk-card__title">{title}</p>
      {statusSentence ? (
        <p className="work-compact-status">{statusSentence}</p>
      ) : null}
      {superseded ? (
        <p role="status" className="work-compact-status">
          {labels.superseded}
        </p>
      ) : null}
      {shown.length === 0 ? (
        <p role="status" className="work-compact-status">
          {labels.empty}
        </p>
      ) : (
        <ul className="work-compact-rows">
          {shown.map((row) => {
            const item = current(row);
            return (
              <li key={cardKey(item)} className="work-compact-row">
                {item.kind !== "task" ? (
                  <span className="work-compact-kind sk-eyebrow">
                    {knownLabel(labels.kind, item.kind)}
                  </span>
                ) : null}
                {onOpenItem && frameFor(item) ? (
                  <RecordTitle
                    item={item}
                    disabled={superseded}
                    onOpen={onOpenItem}
                  />
                ) : (
                  <span className="work-compact-row-title">{item.title}</span>
                )}
                <span className="work-chip">{changeLabel(labels, item)}</span>
                {statusWriter && item.kind === "task" ? (
                  <div
                    role="group"
                    aria-label={labels.statusGroup}
                    className="work-compact-segments"
                  >
                    {TASK_STATUSES.map((value) => (
                      <button
                        key={value}
                        type="button"
                        className="work-compact-action"
                        aria-pressed={item.status === value}
                        disabled={busy !== undefined || superseded}
                        onClick={() => void change(item, value, statusWriter)}
                      >
                        {labels.taskStatus[value]}
                      </button>
                    ))}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {notice ? <NoticeRow notice={notice} locale={labels.dateLocale} /> : null}
      {/* What the list leaves out, only when the card cannot open the list: `showAll` already says it. */}
      {hidden > 0 && !onOpen ? (
        <p className="work-compact-more">
          {fill(labels.more, { count: String(hidden) })}
        </p>
      ) : null}
      {onOpen ? (
        <CardFoot>
          <button
            type="button"
            className="work-compact-action sk-btn--open"
            onClick={onOpen}
            disabled={superseded || opening}
            aria-busy={opening || undefined}
          >
            {opening && openingLabel
              ? openingLabel
              : fill(labels.showAll, { count: String(frame.total) })}
            <ChevronRightIcon />
          </button>
        </CardFoot>
      ) : null}
    </section>
  );
}

/** Translated status, using the Project or Task set by kind; unknown values arrive as they are. */
function statusLabel(
  labels: CardLabels,
  item: Pick<WorkItemRecord, "kind" | "status">,
): string {
  return knownLabel(
    item.kind === "project" ? labels.projectStatus : labels.taskStatus,
    item.status,
  );
}

/**
 * The chip on a row: "Previous → Now" when the record carries the status it had before the change,
 * otherwise only the current status.
 */
function changeLabel(labels: CardLabels, item: WorkItemRecord): string {
  const now = statusLabel(labels, item);
  const before = item.previous_status;
  if (before === undefined || before === null || before === item.status) {
    return now;
  }
  return `${statusLabel(labels, { kind: item.kind, status: before })} → ${now}`;
}

/**
 * The title: the card's word and the number of changes, "Changes (2)"; the bare word when there are none. The number is
 * the server's total, which counts every change even when it sent fewer rows, and "Show all (2)" shows the same one.
 */
function titleFor(labels: CardLabels, total: number): string {
  return total === 0 ? labels.title : `${labels.title} (${total})`;
}

/**
 * The line under the title when every change is a Task and they all have the same status now: where
 * they went ("3 tasks, now In progress"). Otherwise there is no line, since the title already counts.
 * The status check needs every record, so a card that holds only part of the list has none.
 */
function statusSentenceFor(
  labels: CardLabels,
  total: number,
  items: WorkItemRecord[],
): string | undefined {
  if (total === 0) return undefined;
  const first = items[0];
  const sameTaskStatus =
    first !== undefined &&
    items.length === total &&
    items.every((item) => item.kind === "task" && item.status === first.status);
  if (!sameTaskStatus || !first) return undefined;
  const status = statusLabel(labels, first);
  // The sentence reads mid-line (the status sentence), so only the first letter is lowered.
  const lowered = status.charAt(0).toLocaleLowerCase() + status.slice(1);
  return fill(total === 1 ? labels.summaryMovedOne : labels.summaryMovedOther, {
    count: String(total),
    status: lowered,
  });
}

/** Replaces each {name} in a label with its value; a name without a value is left out. */
function fill(template: string, values: Record<string, string>): string {
  return template.replace(
    /\{(\w+)\}/g,
    (_, name: string) => values[name] ?? "",
  );
}
