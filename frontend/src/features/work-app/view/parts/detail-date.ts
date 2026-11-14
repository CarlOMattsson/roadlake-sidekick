import { workDate } from "../../../mcp-apps/ui/due";
import type { WorkLabels } from "../../shared/labels";

/** The date of the Task's date chip, plain, a short date (design system §3, Uppgiftens huvud). */
export function detailDate(dueAt: string, labels: WorkLabels): string {
  return workDate(dueAt, new Date(), labels.dateLocale, {
    inline: true,
    relative: false,
  });
}
