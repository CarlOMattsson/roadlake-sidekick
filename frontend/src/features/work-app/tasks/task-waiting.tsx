import { useEffect, useRef, useState } from "react";
import { ownerDayPlus, ownerDaysToNextMonday } from "../../mcp-apps/ui/due";
import { ChevronDownIcon, PlusIcon } from "../../mcp-apps/ui/icons";
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
import { dateInputValue } from "./task-edit";
import "./task-waiting.css";

/** The days a follow-up is set ahead of today until the user chooses another day. */
const DEFAULT_FOLLOW_UP_DAYS = 3;

/** Which panel the section has open under its chips. */
type Panel = "who" | "followUp" | undefined;

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
 * Who a Task waits on, since when, and the day to follow up, with the controls that change them: the person (a search
 * over the Contacts), the follow-up day (shortcuts and a date) and "I'm no longer waiting". A Task that does not wait
 * offers one quiet line, "I'm waiting on someone", that opens the search; choosing a Contact starts the wait now. Every
 * choice is one update_task through `onWrite` (the frame's own write, so its failure line, version and retry apply).
 * Where the host cannot write (`writable` false) the section only says what the Task waits on, and nothing for a Task
 * that does not wait. A finished Task shows nothing.
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
  const [panel, setPanel] = useState<Panel>();
  const [picked, setPicked] = useState<WorkContact>();
  const [day, setDay] = useState("");
  const search = useContactSearch(transport);
  const searchInput = useRef<HTMLInputElement>(null);
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

  if (!summary)
    return (
      <div className="work-task-waiting">
        {sheet || (
          <button
            type="button"
            className="work-add-row sk-action-row"
            disabled={busy}
            onClick={() => open("who")}
          >
            <PlusIcon />
            {wt.add}
          </button>
        )}
      </div>
    );

  const shortcuts = [
    { label: wt.tomorrow, day: ownerDayPlus(now, 1) },
    { label: wt.inThreeDays, day: ownerDayPlus(now, 3) },
    { label: wt.nextWeek, day: ownerDayPlus(now, ownerDaysToNextMonday(now)) },
  ];
  return (
    <div className="work-task-waiting">
      <p className="work-task-waiting-line">
        <span>{summary.line}</span>{" "}
        {summary.followUp && (
          <span data-tone={summary.reached ? "overdue" : undefined}>
            {summary.followUp}
          </span>
        )}
      </p>
      {writable && (
        <div className="work-task-waiting-actions">
          <button
            type="button"
            className="sk-chip work-prop-chip"
            aria-expanded={panel === "who"}
            disabled={busy}
            onClick={() => (panel === "who" ? close() : open("who"))}
          >
            <span>{wt.changeWho}</span>
            <ChevronDownIcon size={16} />
          </button>
          <button
            type="button"
            className="sk-chip work-prop-chip"
            aria-expanded={panel === "followUp"}
            disabled={busy}
            onClick={() => (panel === "followUp" ? close() : open("followUp"))}
          >
            <span>
              {task.follow_up_at
                ? wt.followUpChip(
                    shortDay(task.follow_up_at, now, t.dateLocale),
                  )
                : wt.setFollowUp}
            </span>
            <ChevronDownIcon size={16} />
          </button>
          <button
            type="button"
            className="sk-chip work-prop-chip"
            disabled={busy}
            onClick={() =>
              onWrite({
                waiting_since: null,
                follow_up_at: null,
                waiting_on_contact_id: null,
              })
            }
          >
            <span>{wt.stop}</span>
          </button>
        </div>
      )}
      {sheet}
      {panel === "followUp" && (
        <KeyScope
          role="group"
          aria-label={wt.followUpPick}
          className="work-task-waiting-panel"
          onEscape={close}
        >
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
              onChange={(event) => setDay(event.target.value)}
            />
            <button
              type="button"
              disabled={busy || !isCompleteDate(day)}
              onClick={() => followUp(day)}
            >
              {t.save}
            </button>
            {task.follow_up_at && (
              <button
                type="button"
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
        </KeyScope>
      )}
    </div>
  );
}
