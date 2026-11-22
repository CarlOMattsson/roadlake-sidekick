import type { TableLabels } from "./table-labels";

export type KindRoom = keyof TableLabels["rooms"];

/**
 * The room a record kind lives in (the "Rum" column), or undefined for a kind no room shows (a reference, an unknown
 * kind). Storage kinds and the activity feed's aggregate types share these names; a run of a process or of an AI step
 * belongs to Work.
 */
export function roomOfKind(kind: string): KindRoom | undefined {
  switch (kind) {
    case "domain":
    case "process":
    case "project":
    case "task":
    case "step":
    case "action":
    case "process_run":
    case "ai_step_run":
      return "work";
    case "contact":
    case "contact_alias":
    case "contact_alias_removed":
    case "contact_link":
    case "contact_task_link":
    case "contact_project_link":
      return "contacts";
    case "journal_entry":
      return "journal";
    case "shopping_item":
    case "shopping_list":
      return "shopping";
    default:
      return undefined;
  }
}
