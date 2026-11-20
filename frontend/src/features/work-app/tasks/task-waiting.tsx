import { useEffect, useId, useRef, useState } from "react";
import { ownerDayPlus, ownerDaysToNextMonday } from "../../mcp-apps/ui/due";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { isCompleteDate } from "../shared/fields";
import type { WorkLabels } from "../shared/labels";
import {
  followUpAtOf,
  shortDay,
  waitingLabelsFor,
  waitingSummary,
} from "../shared/waiting";
import type {
  WorkContact,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "../transport/transport";
import {
  ContactHit,
  ContactSearchSheet,
  useContactSearch,
} from "./contact-search";
import { PropLabel } from "./chip-choices";
import { dateInputValue } from "./task-edit";
import { taskPlaceLabelsFor } from "./task-place-labels";
import "./task-waiting.css";

/** The days a follow-up is set ahead of today until the user chooses another day. */
const DEFAULT_FOLLOW_UP_DAYS = 3;

/** What the row has open under it: the person search, or the actions of a wait. */
type Panel = "who" | "actions" | undefined;

/**
 * The name of the Contact a Task waits on. The caller may know it (`known`: a list record carries it); a Task read with
 * get_task carries only the id, so the name is read from the Contact. A Contact picked here is known at once. Null while
 * unknown, or when the Contact cannot be read, which the line says as "someone".
 */
function useWaitingName(
  transport: WorkTransport,
  id: string | null,
  known: string | null | undefined,
  picked: WorkContact | undefined,
): string | null {
  const [read, setRead] = useState<{ id: string; name: string }>();
  const wanted = id && !known && picked?.id !== id ? id : undefined;
  useEffect(() => {
    if (!wanted) return;
    let current = true;
    transport.getContactContext(wanted).then(
      (context) => {
        if (current)
          setRead({ id: wanted, name: context.contact.display_name });
      },
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [transport, wanted]);
  if (picked && picked.id === id) return picked.display_name;
  if (known) return known;
  return read && read.id === id ? read.name : null;
}

/**
 * Who a Task waits on, since when and the day to follow up, as one row of the property list under the priority row
 * (`Väntar på | Fatima Karimi ⌄`, a second line "sedan idag · följ upp 23 nov", the follow-up part in the overdue tone once
 * its day has come). A Task that does not wait reads `Väntar på | Ingen ⌄`, and its panel is the search over the Contacts;
 * choosing a Contact starts the wait now. The panel of a wait holds "Change person", the follow-up day (shortcuts and a
 * date field that writes when a complete date is chosen, as the due date does) and "I'm no longer waiting". Every choice
 * is one update_task through `onWrite` (the frame's own write, so its failure line, version and retry apply). Escape closes
 * the panel and returns focus to the row. Where the host cannot write (`writable` false) the row only says what the Task
 * waits on, and nothing for a Task that does not wait. A finished Task shows nothing.
 */
export function TaskWaiting({
  task,
  labels: t,
  transport,
  contactName,
  writable,
  busy,
  now = new Date(),
  onWrite,
}: {
  task: WorkTask;
  labels: WorkLabels;
  /** Searches the Contacts and reads the name of the Contact the Task waits on. */
  transport: WorkTransport;
  /** The name of the waiting Contact when the caller already has it. */
  contactName?: string | null;
  /** The host answers update_task. */
  writable: boolean;
  /** A write is running, or the editor is open. */
  busy: boolean;
  /** The instant "today" and the shortcuts are counted from. */
  now?: Date;
  /** Writes the given changes against the Task (update_task). */
  onWrite: (changes: WorkTaskChanges) => void;
}) {
  const wt = waitingLabelsFor(t.dateLocale);
  const rowName = taskPlaceLabelsFor(t.dateLocale).props.waiting;
  const [panel, setPanel] = useState<Panel>();
  const [picked, setPicked] = useState<WorkContact>();
  const [day, setDay] = useState("");
  const search = useContactSearch(transport);
  const searchInput = useRef<HTMLInputElement>(null);
  const row = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const headingId = useId();
  const who = useWaitingName(
    transport,
    task.waiting_on_contact_id ?? null,
    contactName,
    picked,
  );
  const summary = waitingSummary(task, who, now, t.dateLocale);
  const followUpDay = dateInputValue(task.follow_up_at ?? null);
  useEffect(() => {
    if (panel === "who") searchInput.current?.focus();
  }, [panel]);
  if (task.status === "completed" || task.status === "cancelled") return null;
  if (!summary && !writable) return null;

  function open(next: Panel) {
    search.change("");
    setDay(followUpDay || ownerDayPlus(now, DEFAULT_FOLLOW_UP_DAYS));
    setPanel(next);
  }
  function close() {
    setPanel(undefined);
    row.current?.focus();
  }
  function pick(contact: WorkContact) {
    setPicked(contact);
    close();
    onWrite({
      waiting_on_contact_id: contact.id,
      // The wait starts now unless it already runs.
      ...(task.waiting_since ? {} : { waiting_since: now.toISOString() }),
    });
  }
  function followUp(chosen: string) {
    close();
    onWrite({ follow_up_at: followUpAtOf(chosen) });
  }

  // The words of the row: who, then since when and the follow-up day, each once.
  const name = who ?? wt.someone;
  const sinceDay = task.waiting_since
    ? shortDay(task.waiting_since, now, t.dateLocale)
    : "";
  const sinceText = sinceDay ? wt.since(sinceDay) : null;
  const meta = [sinceText, summary?.followUp].filter(
    (part): part is string => !!part,
  );
  const value = summary ? (
    <span className="work-waiting-value">
      <span>{name}</span>
      {meta.length > 0 && (
        <span className="work-waiting-meta">
          {sinceText}
          {sinceText && summary.followUp && " · "}
          {summary.followUp && (
            <span data-tone={summary.reached ? "overdue" : undefined}>
              {summary.followUp}
            </span>
          )}
        </span>
      )}
    </span>
  ) : (
    <span className="work-waiting-none">{wt.none}</span>
  );

  if (!writable)
    return (
      <div className="work-task-waiting">
        <span className="sk-chip work-prop-chip work-prop-static">
          <PropLabel text={rowName} />
          {value}
        </span>
      </div>
    );

  const sheet = panel === "who" && (
    <ContactSearchSheet
      title={wt.pickWho}
      labels={t}
      search={search}
      busy={false}
      inputRef={searchInput}
      onClose={close}
      renderHit={(contact) => (
        <ContactHit
          contact={contact}
          disabled={busy}
          busy={false}
          onPick={() => pick(contact)}
        />
      )}
    />
  );
  const shortcuts = [
    { label: wt.tomorrow, day: ownerDayPlus(now, 1) },
    { label: wt.inThreeDays, day: ownerDayPlus(now, 3) },
    { label: wt.nextWeek, day: ownerDayPlus(now, ownerDaysToNextMonday(now)) },
  ];
  const actions = summary ? "actions" : "who";
  return (
    <KeyScope
      className="work-task-waiting"
      onEscape={panel ? close : undefined}
    >
      <button
        ref={row}
        type="button"
        className="sk-chip work-prop-chip"
        data-empty={summary ? undefined : "true"}
        aria-label={`${rowName}: ${summary ? [name, ...meta].join(", ") : wt.none}`}
        aria-expanded={panel !== undefined}
        aria-controls={panel === "actions" ? panelId : undefined}
        disabled={busy}
        onClick={() => (panel ? close() : open(actions))}
      >
        <PropLabel text={rowName} />
        {value}
        <ChevronDownIcon size={16} />
      </button>
      {sheet}
      {panel === "actions" && (
        <div
          id={panelId}
          role="group"
          aria-label={rowName}
          className="work-task-waiting-panel"
        >
          <div className="work-task-waiting-actions">
            <button
              type="button"
              className="sk-chip"
              disabled={busy}
              onClick={() => open("who")}
            >
              {wt.changeWho}
            </button>
            <button
              type="button"
              className="sk-chip"
              disabled={busy}
              onClick={() => {
                close();
                onWrite({
                  waiting_since: null,
                  follow_up_at: null,
                  waiting_on_contact_id: null,
                });
              }}
            >
              {wt.stop}
            </button>
          </div>
          <div role="group" aria-labelledby={headingId}>
            <span id={headingId} className="work-task-waiting-heading">
              {wt.editFollowUp}
            </span>
            <div className="work-task-waiting-shortcuts">
              {shortcuts.map((shortcut) => (
                <button
                  key={shortcut.label}
                  type="button"
                  className="sk-chip"
                  disabled={busy}
                  onClick={() => followUp(shortcut.day)}
                >
                  {shortcut.label}
                </button>
              ))}
            </div>
            <div className="work-task-waiting-date">
              <input
                type="date"
                aria-label={wt.followUpDay}
                value={day}
                disabled={busy}
                onChange={(event) => {
                  const chosen = event.target.value;
                  setDay(chosen);
                  // Saves as the due date does: when a complete date stands, no button.
                  if (isCompleteDate(chosen)) followUp(chosen);
                }}
              />
              {task.follow_up_at && (
                <button
                  type="button"
                  className="sk-chip"
                  disabled={busy}
                  onClick={() => {
                    close();
                    onWrite({ follow_up_at: null });
                  }}
                >
                  {wt.clearFollowUp}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </KeyScope>
  );
}
