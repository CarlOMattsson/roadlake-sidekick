import { relativeDue } from "../../mcp-apps/ui/due";
import type { WorkLabels } from "../labels";

/** The due date of a list row as plain text: "5 dagar försenad", "Idag", "fre 6 nov". Red when overdue. */
export function TaskDue({
  dueAt,
  labels,
}: {
  dueAt: string;
  labels: WorkLabels;
}) {
  const locale = labels.dateLocale.startsWith("sv") ? "sv" : "en";
  const due = relativeDue(dueAt, new Date(), locale);
  return (
    <time dateTime={dueAt} data-tone={due.tone}>
      {due.text}
    </time>
  );
}
