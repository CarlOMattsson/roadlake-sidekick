/**
 * Work App record types: the Task, Project, Step, Contact and other records the views read, derived
 * from contracts/mcp-tools.generated.json through the generated tool types. Extra fields are allowed.
 */
import type { Item, WithOptional } from "../../lib/mcp/derived";
import type {
  ToolInputs,
  ToolResults,
} from "../../lib/mcp/tool-results.generated";

type Results = ToolResults;
type Inputs = ToolInputs;

type TaskChanges = Inputs["update_task"]["changes"];
export type TaskStatusValue = NonNullable<TaskChanges["status"]>;
export const TASK_STATUSES = [
  "todo",
  "in_progress",
  "blocked",
  "completed",
] as const satisfies readonly TaskStatusValue[];
/** Whether a value is one of the Task statuses. */
export function isTaskStatus(value: string): value is TaskStatusValue {
  return (TASK_STATUSES as readonly string[]).includes(value);
}
/**
 * One Task as get_task returns it, the fields the views read. The fields below are optional
 * because other tools and an older server leave them out: `project_title`, `steps_done` and
 * `steps_total` are get_task only.
 */
export type WorkTask = WithOptional<
  Pick<
    Results["get_task"]["task"],
    | "id"
    | "title"
    | "status"
    | "due_at"
    | "version"
    | "description"
    | "priority"
    | "project_id"
    | "domain_id"
    | "process_id"
    | "recurrence"
    | "project_title"
    | "steps_done"
    | "steps_total"
    | "last_completed_at"
  >,
  | "description"
  | "priority"
  | "project_id"
  | "domain_id"
  | "process_id"
  | "recurrence"
  | "project_title"
  | "steps_done"
  | "steps_total"
  | "last_completed_at"
>;
/**
 * Fields update_task accepts. An omitted key is left unchanged; null clears due_at, domain_id or
 * description.
 */
export type WorkTaskChanges = TaskChanges;
/** One Domain as list_domains returns it (DomainRecord); only the fields the sorting view shows. */
export type WorkDomain = WithOptional<
  Pick<Item<Results["list_domains"]["domains"]>, "id" | "name" | "accent">,
  "accent"
>;
/** One page of Tasks as list_tasks with unsorted returns them: Tasks with no Domain, Project or Process. */
export type WorkUnsortedPage = {
  items: WorkTask[];
  next_cursor: string | null;
};
/**
 * Fields create_task accepts. Without project_id or process_id the Task stands alone (unsorted); due_at is an
 * instant, and null or absent means no due date.
 */
export type WorkTaskCreate = Omit<Inputs["create_task"], "idempotency_key">;
/**
 * The eight domain accent names (see docs/decisions/log.md D-061). Each has --sk-accent-<name>-line, -bg and -fg in
 * mcp-apps/ui/tokens.css; the server sends one of these or null.
 */
export type DomainAccent = NonNullable<
  Results["get_domain"]["domain"]["accent"]
>;
export const DOMAIN_ACCENTS = [
  "slate",
  "blue",
  "teal",
  "green",
  "amber",
  "orange",
  "rose",
  "violet",
] as const satisfies readonly DomainAccent[];
/** The accent name of a server value, or null when it is missing or not one of the eight names. */
export function domainAccentOf(value: unknown): DomainAccent | null {
  return DOMAIN_ACCENTS.find((name) => name === value) ?? null;
}

export type ProjectStatusValue = NonNullable<
  Inputs["update_project"]["changes"]["status"]
>;
export const PROJECT_STATUSES = [
  "active",
  "paused",
  "completed",
] as const satisfies readonly ProjectStatusValue[];

/** One Project as get_project returns it; the Task counts are get_project only. */
export type WorkProject = WithOptional<
  Pick<
    Results["get_project"]["project"],
    | "id"
    | "title"
    | "status"
    | "description"
    | "start_date"
    | "target_date"
    | "version"
    | "domain_id"
    | "tasks_done"
    | "tasks_total"
    | "tasks_overdue"
  >,
  "domain_id" | "tasks_done" | "tasks_total" | "tasks_overdue"
>;
/**
 * Fields update_project accepts. An omitted key is left unchanged; null clears a date or the
 * description. Dates are YYYY-MM-DD and are sent as they are, without a time zone conversion.
 */
export type WorkProjectChanges = Inputs["update_project"]["changes"];
/** One Step as the Step tools return it. */
export type WorkStep = WithOptional<
  Pick<
    Results["create_task_step"]["step"],
    | "id"
    | "title"
    | "status"
    | "due_at"
    | "version"
    | "position"
    | "archived_at"
  >,
  "position" | "archived_at"
>;
/** One Action under a Step as list_step_actions and the Action writes return it (ActionRecord). */
export type WorkAction = WithOptional<
  Pick<
    Results["archive_step_action"]["action"],
    | "id"
    | "step_id"
    | "title"
    | "status"
    | "due_at"
    | "version"
    | "position"
    | "note"
    | "archived_at"
  >,
  "position" | "note" | "archived_at"
>;
export type WorkActionPage = {
  items: WorkAction[];
  next_cursor: string | null;
};
/** One item of a reorder write: the id of the Step or Action and the version the view holds. */
export type WorkOrderItem = Item<Inputs["reorder_task_steps"]["items"]>;
/** The closed filter set a saved Work view may name (SavedViewDefinitionRecord). */
export type WorkSavedViewDefinition = WithOptional<
  Omit<
    Results["create_saved_work_view"]["saved_view"]["definition"],
    "name" | "version"
  >,
  | "q"
  | "status"
  | "priority"
  | "priorities"
  | "tags"
  | "tag_match"
  | "archive"
  | "actionable"
  | "attention"
  | "estimate"
  | "waiting"
  | "kind"
  | "sort"
  | "group"
>;
/** One saved Work view (SavedWorkViewRecord). */
export type WorkSavedView = Omit<
  Results["create_saved_work_view"]["saved_view"],
  "definition" | "archived_at"
> & {
  definition: WorkSavedViewDefinition;
  archived_at?: string | null;
};
/** One external pointer on a Task (mail, event or document): a stale snapshot, never the content. */
export type WorkExternalReference = WithOptional<
  Pick<
    Item<Results["list_task_external_references"]["items"]>,
    | "id"
    | "kind"
    | "provider"
    | "account_ref"
    | "external_id"
    | "instance_ref"
    | "title"
    | "url"
    | "occurs_at"
    | "version"
  >,
  "version"
>;
export type WorkExternalReferencePage = {
  items: WorkExternalReference[];
  next_cursor: string | null;
};
/** A Domain as get_domain returns it (DomainRecord). */
export type WorkDomainRecord = WithOptional<
  Pick<
    Results["get_domain"]["domain"],
    | "id"
    | "name"
    | "description"
    | "status"
    | "accent"
    | "tags"
    | "review_cadence"
    | "last_reviewed_at"
    | "version"
  >,
  "accent" | "tags" | "review_cadence" | "last_reviewed_at"
>;
/** A Process as get_process returns it (ProcessRecord). */
export type WorkProcessRecord = WithOptional<
  Pick<
    Results["get_process"]["process"],
    | "id"
    | "domain_id"
    | "name"
    | "description"
    | "status"
    | "cadence"
    | "tags"
    | "version"
  >,
  "cadence" | "tags"
>;
export type WorkStepPage = {
  items: WorkStep[];
  next_cursor: string | null;
};
export type WorkTaskSummaryPage = {
  items: WorkTaskSummary[];
  next_cursor: string | null;
  /** True when the server cut the list and has no cursor for the rest (a Process's Tasks on the phone). */
  truncated?: boolean;
};
export type WorkContact = { id: string; display_name: string };
export type WorkContactPage = {
  items: WorkContact[];
  next_cursor: string | null;
};
/** One row of list_contacts (ContactSummaryRecord); the profile fields are absent in older results. */
export type WorkContactSummary = WithOptional<
  Pick<
    Item<Results["list_contacts"]["contacts"]>,
    | "id"
    | "display_name"
    | "archived"
    | "relationship"
    | "organization"
    | "role"
  >,
  "archived" | "relationship" | "organization" | "role"
>;
/**
 * One page of the Contact list with the search it was read with. A cursor belongs to that search
 * (q and include_archived), so Show more always repeats it.
 */
export type WorkContactsPage = {
  items: WorkContactSummary[];
  next_cursor: string | null;
  /** The trimmed search text; empty means every Contact. */
  q: string;
  includeArchived: boolean;
};
/** Fields create_contact takes from this app; email is omitted when empty. */
export type WorkContactCreate = Pick<
  Inputs["create_contact"],
  "display_name" | "email"
>;
export type WorkContactAlias = Pick<
  Item<Results["create_contact"]["contact"]["aliases"]>,
  "id" | "value" | "created_at"
>;
/** A Contact as get_contact_context and the contact writes return it (ContactRecord). */
export type WorkContactRecord = Pick<
  Results["create_contact"]["contact"],
  | "id"
  | "display_name"
  | "email"
  | "phone"
  | "context_note"
  | "relationship"
  | "organization"
  | "role"
  | "address"
  | "aliases"
  | "archived"
  | "archived_at"
  | "version"
>;
/**
 * Fields update_contact accepts. An omitted key is left unchanged; null clears email, phone or the
 * context note. The display name is sent only as a non-empty string. The profile text fields
 * (relationship, organization, role, address) clear with an empty string, which the server stores
 * as no value.
 */
export type WorkContactChanges = Inputs["update_contact"]["changes"];
type ContactContextResult = Results["get_contact_context"];
export type WorkProjectSummary = Pick<
  Item<ContactContextResult["projects"]["items"]>,
  "id" | "title" | "status"
>;
export type WorkTaskSummary = Pick<
  Item<Results["list_tasks"]["tasks"]>,
  "id" | "title" | "status" | "due_at"
>;
/** One Journal entry linked to a Contact, as get_contact_context lists it: id, date and title only. */
export type WorkJournalEntryLink = Item<
  ContactContextResult["journal_entries"]["items"]
>;
/**
 * The newest Journal entries linked to a Contact (JournalEntryContextRecord). `readable` false means the
 * session may not read the journal; then `items` is empty and nothing about the entries is implied.
 */
export type WorkJournalEntries = ContactContextResult["journal_entries"];
export type WorkContactContext = {
  contact: WorkContactRecord;
  projects: { items: WorkProjectSummary[]; next_cursor?: string | null };
  tasks: { items: WorkTaskSummary[]; next_cursor: string | null };
  /** The newest linked Journal entries. Optional: an absent or unreadable part shows no Journal section. */
  journal_entries?: WorkJournalEntries;
};
/** One Task of a board column as the reorder writes it: its id and the version the board showed. */
export type WorkBoardPlacementItem = { taskId: string; version: number };
/** One Task as reorder_work_board_column returns it (BoardPlacementRecord). */
export type WorkBoardPlacement = Item<
  Results["reorder_work_board_column"]["items"]
>;
/** What the contact and reference link tools answer: whether the link exists afterwards. */
export type WorkLinkResult = Pick<Results["link_contact_to_task"], "linked">;
export type WorkUnlinkReferenceResult = Pick<
  Results["unlink_external_reference_from_task"],
  "linked" | "reference_removed"
>;
export type WorkRescheduleResult = Pick<Results["reschedule_tasks"], "count">;
