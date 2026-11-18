import type { WorkItemRecord } from "../../transport/transport";
import { capital, waitingSummary } from "../../shared/waiting";

/**
 * The line a waiting Task adds under its meta line: who it waits on and since when, and the follow-up day ("Väntar på
 * Anders sedan 13 nov · följ upp 17 nov"). A follow-up that has come is in the overdue tone. A Task that stands in the
 * agenda on its follow-up day, with no due date of its own that is earlier, starts the line with the follow-up
 * ("Följ upp igår · Väntar på Anders sedan 13 nov"), so it does not read as an ordinary overdue Task. Nothing for a Task
 * that is not waiting.
 */
export function WaitingMeta({
  item,
  now,
  dateLocale,
}: {
  item: WorkItemRecord;
  now: Date;
  dateLocale: string;
}) {
  if (
    item.kind !== "task" ||
    !item.waiting ||
    item.status === "completed" ||
    item.status === "cancelled"
  )
    return null;
  const summary = waitingSummary(
    item,
    item.waiting_on_contact_name?.trim() || null,
    now,
    dateLocale,
  );
  if (!summary) return null;
  const follow = summary.followUp && (
    <span data-tone={summary.reached ? "overdue" : undefined}>
      {summary.followUpFirst ? capital(summary.followUp) : summary.followUp}
    </span>
  );
  const line = <span>{summary.line}</span>;
  return (
    <p className="work-agenda-waiting">
      {summary.followUpFirst ? (
        <>
          {follow} {line}
        </>
      ) : (
        <>
          {line} {follow}
        </>
      )}
    </p>
  );
}
