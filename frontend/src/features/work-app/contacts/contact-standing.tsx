import { workDate } from "../../mcp-apps/ui/due";
import { ClockIcon } from "../../mcp-apps/ui/icons";
import { OpenChevron } from "../tasks/task-detail-controls";
import { LONG_WAIT_DAYS, waitedDays } from "../shared/waiting";
import type {
  WorkJournalEntries,
  WorkTaskSummary,
} from "../transport/transport";
import type { WorkFrame } from "../transport/transport";
import { contactsRoomLabelsFor } from "./contacts-room-labels";

/**
 * The waiting fields of a Task as get_contact_context lists it (TaskSummaryRecord): whether the Task waits on this
 * Contact, and since when. The shared Task summary type leaves them out, so they are read here, defensively.
 */
function waitOf(task: WorkTaskSummary): { since: string | null } | null {
  const fields = task as {
    waiting_on_contact?: unknown;
    waiting_since?: unknown;
  };
  if (fields.waiting_on_contact !== true) return null;
  return {
    since:
      typeof fields.waiting_since === "string" ? fields.waiting_since : null,
  };
}

/** The Tasks that wait on the Contact, the longest wait first; a wait without a date comes last. */
export function waitingTasks(
  tasks: readonly WorkTaskSummary[],
  now: Date,
): { task: WorkTaskSummary; days: number | null }[] {
  return tasks
    .flatMap((task) => {
      const wait = waitOf(task);
      return wait ? [{ task, days: waitedDays(wait.since, now) }] : [];
    })
    .sort((a, b) => (b.days ?? -1) - (a.days ?? -1));
}

/**
 * Where you stand with the Contact, at the top of her card (the question before a meeting): "You are waiting on Erik
 * for 9 days" as a row that opens the Task waited on longest (its title under it, and how many more wait), and when you
 * last had contact as far as the journal knows (the newest linked entry's day). A wait of LONG_WAIT_DAYS or more takes
 * the overdue tone, as in the agenda's waiting view. Nothing to say, no block.
 */
export function ContactStanding({
  name,
  tasks,
  journal,
  dateLocale,
  onOpen,
  now = new Date(),
}: {
  name: string;
  tasks: readonly WorkTaskSummary[];
  journal?: WorkJournalEntries;
  dateLocale: string;
  onOpen: (frame: WorkFrame, label?: string) => void;
  now?: Date;
}) {
  const words = contactsRoomLabelsFor(dateLocale);
  const first = name.split(/\s+/u)[0] ?? name;
  const waits = waitingTasks(tasks, now);
  const longest = waits[0];
  const newest = journal?.readable ? journal.items[0] : undefined;
  const lastDay = newest
    ? workDate(newest.journal_date, now, dateLocale, { inline: true })
    : "";
  if (!longest && !lastDay) return null;
  return (
    <div className="work-contact-standing">
      {longest && (
        <button
          type="button"
          className="work-contact-waiting"
          data-tone={
            longest.days !== null && longest.days >= LONG_WAIT_DAYS
              ? "overdue"
              : undefined
          }
          onClick={() =>
            onOpen({ kind: "task", id: longest.task.id }, longest.task.title)
          }
        >
          <span className="work-contact-waiting-clock">
            <ClockIcon />
          </span>
          <span className="work-contact-waiting-body">
            <span className="work-contact-waiting-line">
              {words.waitingOn(first, longest.days)}
            </span>
            <span className="work-contact-waiting-task">
              {words.waitingTask(longest.task.title, waits.length - 1)}
            </span>
          </span>
          <OpenChevron />
        </button>
      )}
      {lastDay && (
        <p className="work-contact-last">
          <time dateTime={newest?.journal_date}>
            {words.lastInJournal(lastDay)}
          </time>
        </p>
      )}
    </div>
  );
}
