/**
 * Work App navigation frames and the filters of the board and agenda reads. A frame is the item
 * currently shown or previously visited; a board, agenda or Contact list frame keeps its page.
 */
import type { Item, WithOptional } from "../../../lib/mcp/derived";
import type { ToolResults } from "../../../lib/mcp/tool-results.generated";
import type {
  WorkContactContext,
  WorkContactRecord,
  WorkContactsPage,
  WorkProcessRecord,
  WorkProject,
  WorkTask,
} from "./transport-records";

type Results = ToolResults;

type AgendaRecord = Item<Results["get_work_agenda"]["items"]>;
/**
 * One Work record as get_work_board and get_work_agenda return it (WorkItemView). Only the fields
 * the board and the agenda show are typed here, and only the identity and text are required: an
 * older server may leave the rest out.
 */
export type WorkItemRecord = Pick<
  AgendaRecord,
  "kind" | "id" | "title" | "status"
> &
  Partial<
    Pick<
      AgendaRecord,
      | "due_at"
      | "version"
      | "project_id"
      | "project_title"
      | "task_id"
      | "priority"
      | "domain_accent"
      | "agenda_group"
      | "waiting"
      | "waiting_since"
      | "waiting_on_contact_id"
      | "waiting_on_contact_name"
      | "follow_up_at"
      | "follow_up_due"
      | "recurrence"
      | "last_completed_at"
    >
  > & {
    /**
     * Status before the change, when the record carries it. show_work_changes does not send it
     * today, so work cards show only the current status until the server adds it.
     */
    previous_status?: string | null;
  };
export type WorkBoardPage = {
  columns: Record<string, WorkItemRecord[]>;
  next_cursor: Results["get_work_board"]["next_cursor"];
  /**
   * The status columns the user has ordered (a drag on the board, Flytta upp/ned). The phone's Status list keeps the
   * server's order there and sorts the other sections by due date. Missing (an older
   * server) is [].
   */
  manually_ordered?: Results["get_work_board"]["manually_ordered"];
};
export type WorkAgendaPage = {
  items: WorkItemRecord[];
  next_cursor: Results["get_work_agenda"]["next_cursor"];
};
/** The filters a board or agenda read was made with; "Uppdatera" and "Visa fler" repeat them. */
export type WorkFilters = Record<string, string | string[]>;
/** Filters both get_work_board and get_work_agenda take. */
const SHARED_FILTER_KEYS = [
  "q",
  "status",
  "priority",
  "tags",
  "tag_match",
  "archive",
  "actionable",
  "attention",
  "estimate",
  "waiting",
] as const;
/** Filters get_work_board takes: the shared ones and project_id, so a Project's board stays one Project's. */
export const BOARD_FILTER_KEYS = [...SHARED_FILTER_KEYS, "project_id"] as const;
/** Filters get_work_agenda takes: the shared ones plus kind, sort and group. It has no project_id. */
export const AGENDA_FILTER_KEYS = [
  ...SHARED_FILTER_KEYS,
  "kind",
  "sort",
  "group",
] as const;
/**
 * A Task, Contact or Project frame. The optional data is the record the opening tool result carried
 * (validated); without it the card loads the record as before.
 */
export type WorkEntityFrame =
  | { kind: "task"; id: string; task?: WorkTask }
  | { kind: "contact"; id: string; context?: WorkContactContext }
  | { kind: "project"; id: string; project?: WorkProject }
  /** A Process page: the Process and its Tasks (the Process's sibling of the Project page). */
  | { kind: "process"; id: string; process?: WorkProcessRecord };
export type WorkBoardFrame = {
  kind: "board";
  filters: WorkFilters;
  page: WorkBoardPage;
  /** The text of the tab row's search the page was read with (sent as `q`); absent when the page is not a search. */
  search?: string;
  /** The segment the single-column board shows (a status key); kept when a Task is opened and closed. */
  column?: string;
};
export type WorkAgendaFrame = {
  kind: "agenda";
  filters: WorkFilters;
  page: WorkAgendaPage;
};
type HierarchyResult = Results["get_work_hierarchy"];
/** One node of get_work_hierarchy (HierarchyNodeRecord); `status`, `version` and `accent` are optional. */
export type WorkHierarchyNode = WithOptional<
  Item<HierarchyResult["nodes"]>,
  "status" | "version" | "accent"
>;
/** One Task under a hierarchy Project or Process (HierarchyTaskRecord), with its Steps in order. `parent_id` is the Project, or else the Process, the Task belongs to. */
export type WorkHierarchyTask = Item<NonNullable<HierarchyResult["tasks"]>>;
/** One Step under a hierarchy Task (HierarchyStepRecord). */
export type WorkHierarchyStep = Item<WorkHierarchyTask["steps"]>;
/**
 * The Work hierarchy as get_work_hierarchy returns it: nodes in the server's order, with
 * `truncated` true when the server cut the list. `tasks` is present only when the tool was
 * called with include_tasks. `next_cursor` is present only when another page of nodes follows; "Show more" reads it.
 */
export type WorkHierarchyFrame = {
  kind: "hierarchy";
  nodes: WorkHierarchyNode[];
  truncated: boolean;
  next_cursor?: string;
  tasks?: WorkHierarchyTask[];
};
/**
 * The Contact list. `q` is the text in the search field and `includeArchived` the switch; `page`
 * is the last page read, absent until the first read has answered. Going back to the frame shows
 * the same search and page without a new read.
 */
export type WorkContactsFrame = {
  kind: "contacts";
  q: string;
  includeArchived: boolean;
  page?: WorkContactsPage;
};
/**
 * Inline card for a work_changes envelope (show_work_changes): the Work records the server read
 * for the owner. `total` is the full count for "+N"; `truncated` says the server cut the list.
 */
export type WorkCardFrame = {
  kind: "card";
  items: WorkItemRecord[];
  total: number;
  truncated: boolean;
  /**
   * Server-issued UTC ISO time of the card (`card.issued_at`). Ranks copies of the card; without a
   * valid value the card is never superseded.
   */
  issuedAt?: string;
};
/** Compact card for one record a tool result carries alone; a Contact for now. */
export type WorkCompactFrame = {
  kind: "compact";
  entity: "contact";
  contact: WorkContactRecord;
};
/** Shown when the tool result was an error (isError); carries no data. */
export type WorkErrorFrame = { kind: "error" };
/**
 * One navigation frame: the item currently shown or previously visited. A board, agenda or
 * Contact list frame keeps its page, so going back to it shows the same page without a new read.
 */
export type WorkFrame =
  | WorkEntityFrame
  | WorkBoardFrame
  | WorkAgendaFrame
  | WorkHierarchyFrame
  | WorkContactsFrame
  | WorkCardFrame
  | WorkCompactFrame
  | WorkErrorFrame;
