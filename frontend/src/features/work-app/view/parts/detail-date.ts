import { dueClockText, workDate } from "../../../mcp-apps/ui/due";
import type { WorkLabels } from "../../shared/labels";

/**
 * The date of the Task's date chip, plain, a short date (design system §3, Uppgiftens huvud), followed by the clock
 * time when the Task has one ("18 nov kl 17:30").
 */
export function detailDate(dueAt: string, labels: WorkLabels): string {
  const date = workDate(dueAt, new Date(), labels.dateLocale, {
    inline: true,
    relative: false,
  });
  const clock = dueClockText(dueAt, labels.dateLocale);
  return clock ? `${date} ${clock}` : date;
}
