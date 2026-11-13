import { relativeDue, workDate } from "../../mcp-apps/ui/due";
import type { WorkLabels } from "../shared/labels";

/**
 * The due date of a list row as plain text: "5 dagar försenad", "Idag", "Fre 6 nov". It starts the row's meta line, so
 * it starts with a capital like every other line; red when overdue.
 */
export function TaskDue({
  dueAt,
  labels,
}: {
  dueAt: string;
  labels: WorkLabels;
}) {
  const now = new Date();
  const locale = labels.dateLocale.startsWith("sv") ? "sv" : "en";
  const due = relativeDue(dueAt, now, locale);
  return (
    <time dateTime={dueAt} data-tone={due.tone}>
      {due.tone === "overdue"
        ? due.text
        : workDate(dueAt, now, labels.dateLocale)}
    </time>
  );
}
