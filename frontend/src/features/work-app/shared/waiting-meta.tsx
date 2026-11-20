import type { WorkItemRecord } from "../transport/transport";
import { followUpLeads, itemWaitingSummary } from "./waiting";

/**
 * The line a waiting Task adds under its meta line, on the Agenda and on the Status board: who it waits on and since
 * when, then the one date its meta line does not carry. Each part is a flex item of the meta line's own class, so the
 * "·" is drawn in CSS and a wrapped line never starts with one.
 *
 * In an agenda group (`group` given) a Task whose follow-up is the earlier date stands there by it and its meta line
 * leads with "Följ upp igår" (RecordMeta), so this line ends with the due date instead ("Väntar på Anders sedan 13 nov
 * · förfaller imorgon"). Everywhere else the meta line leads with the due date and this line ends with the follow-up
 * ("… · följ upp 17 nov"), in the overdue tone once it has come. Nothing for a Task that is not waiting.
 */
export function WaitingMeta({
  item,
  now,
  dateLocale,
  group,
}: {
  item: WorkItemRecord;
  now: Date;
  dateLocale: string;
  /** The agenda group of the row; none on the board, where the meta line leads with the due date. */
  group?: string | null;
}) {
  const summary = itemWaitingSummary(item, now, dateLocale);
  if (!summary) return null;
  const leads = followUpLeads(summary, group);
  const last = leads ? summary.due : summary.followUp;
  return (
    <p className="work-card-meta work-agenda-waiting">
      <span>{summary.line}</span>
      {last ? (
        <span data-tone={!leads && summary.reached ? "overdue" : undefined}>
          {last}
        </span>
      ) : null}
    </p>
  );
}
