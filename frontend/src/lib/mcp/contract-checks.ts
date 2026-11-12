/**
 * Compile-time checks that the transport types stay in step with the MCP tool schemas.
 *
 * `ToolResults` and `ToolInputs` are generated from contracts/mcp-tools.generated.json (see
 * scripts/generate-tool-types.mjs). The transport types of the apps (`features/*\/transport.ts`)
 * are derived from them, not restated: a field the backend renames, retypes or drops breaks
 * `npm run typecheck` where the transport type names it. A transport type may be looser than the
 * contract in deliberate places (`WithOptional` for a field an older server leaves out) but never
 * wider than what the tool sends.
 *
 * Derivation cannot cover three things, which this file does:
 *  - a type derived from one tool that other tools also feed (the Task read by get_task and
 *    returned by update_task, create_task and list_tasks): each assertion says the other tool's
 *    output can be assigned to the type the app reads;
 *  - the runtime lists the app keeps (statuses, accents, key point kinds, memory domains): each is
 *    asserted to equal the contract's union, so a value the backend adds or drops fails here;
 *  - the guard assertions at the end, which prove that `Accepts` and `Covers` can fail.
 *
 * To see why an assertion fails, assign the generated type to the transport type in a scratch file
 * (`const x: WorkTask = {} as ToolResults["update_task"]["task"]`): tsc then names the field.
 *
 * The file has no runtime code: it is checked by tsc and erased from the bundle.
 */
import type { MEMORY_DOMAINS } from "../../features/control-app/transport";
import type { KEY_POINT_KINDS } from "../../features/journal-app/draft-review-parts/edit-values";
import type {
  JournalDay,
  JournalDraftRead,
  JournalDraftStatus,
  JournalEntry,
  JournalFinalizeResult,
} from "../../features/journal-app/transport";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingList,
} from "../../features/shopping-app/transport";
import type {
  DOMAIN_ACCENTS,
  PROJECT_STATUSES,
  TASK_STATUSES,
  WorkAction,
  WorkActionPage,
  WorkAgendaPage,
  WorkBoardPage,
  WorkContactContext,
  WorkContactRecord,
  WorkDomainRecord,
  WorkExternalReference,
  WorkItemRecord,
  WorkLinkResult,
  WorkProject,
  WorkSavedView,
  WorkSavedViewDefinition,
  WorkStep,
  WorkStepPage,
  WorkTask,
  WorkUnlinkReferenceResult,
} from "../../features/work-app/transport/transport";
import type { Item } from "./derived";
import type { ToolInputs, ToolResults } from "./tool-results.generated";

/** Fails to compile unless T is the literal type true. */
type Assert<T extends true> = T;
/** Whether every value of Server can be assigned to Client (server to client direction). */
type Accepts<Client, Server> = [Server] extends [Client] ? true : false;
/** Whether the Client type names no top-level key the Server type lacks (catches a renamed field). */
type Covers<Client, Server> = [Exclude<keyof Client, keyof Server>] extends [
  never,
]
  ? true
  : false;
/** Whether two unions hold exactly the same members. */
type SameUnion<A, B> = [A] extends [B]
  ? [B] extends [A]
    ? true
    : false
  : false;

type Results = ToolResults;
type Inputs = ToolInputs;

/** Shopping room: the item, list and list page, read by one tool and returned by others. */
export type ShoppingChecks = [
  Assert<Accepts<ShoppingDetail, Results["get_shopping_list"]>>,
  Assert<Accepts<ShoppingList, Item<Results["list_shopping_lists"]["lists"]>>>,
  Assert<
    Accepts<ShoppingList, Results["create_shopping_list"]["shopping_list"]>
  >,
  Assert<
    Accepts<ShoppingList, Results["update_shopping_list"]["shopping_list"]>
  >,
  Assert<Accepts<ShoppingItem, Results["set_shopping_item_purchased"]["item"]>>,
  Assert<Accepts<ShoppingItem, Results["update_shopping_item"]["item"]>>,
  Assert<
    Accepts<ShoppingItem, Item<Results["add_shopping_items"]["items"]>["item"]>
  >,
];

/** Journal room: the entry, day, draft and finalize result across the tools that return them. */
export type JournalChecks = [
  Assert<Accepts<JournalDay, Results["get_journal_day"]>>,
  Assert<Accepts<JournalEntry, Results["get_journal_entry"]["entry"]>>,
  Assert<Accepts<JournalEntry, Results["update_journal_entry"]["entry"]>>,
  Assert<Accepts<JournalEntry, Results["write_journal_entry"]["entry"]>>,
  Assert<
    Accepts<JournalEntry, Item<Results["list_journal_entries"]["entries"]>>
  >,
  Assert<Accepts<JournalDraftRead, Results["get_journal_draft"]>>,
  Assert<Accepts<JournalDraftStatus, Results["update_journal_draft"]>>,
  Assert<Accepts<JournalDraftStatus, Results["reject_journal_draft"]>>,
  Assert<Accepts<JournalFinalizeResult, Results["finalize_journal_draft"]>>,
];

/** Work app: Tasks, Projects, Steps, Actions, Contacts, board, agenda and saved views. */
export type WorkChecks = [
  // project_title, steps_done and steps_total are get_task only (optional on WorkTask), so the
  // other Task tools are assigned to the same type.
  Assert<Accepts<WorkTask, Results["update_task"]["task"]>>,
  Assert<Accepts<WorkTask, Results["create_task"]["task"]>>,
  Assert<Accepts<WorkTask, Item<Results["list_tasks"]["tasks"]>>>,
  // tasks_done, tasks_total and tasks_overdue are get_project only.
  Assert<Accepts<WorkProject, Results["update_project"]["project"]>>,
  Assert<Accepts<WorkDomainRecord, Results["create_domain"]["domain"]>>,
  Assert<Accepts<WorkStepPage, Results["list_task_steps"]>>,
  Assert<Accepts<WorkStepPage, Results["reorder_task_steps"]>>,
  Assert<Accepts<WorkStep, Results["complete_task_step"]["step"]>>,
  Assert<Accepts<WorkStep, Results["update_task_step"]["step"]>>,
  Assert<Accepts<WorkStep, Results["archive_task_step"]["step"]>>,
  Assert<Accepts<WorkStep, Results["restore_task_step"]["step"]>>,
  Assert<Accepts<WorkActionPage, Results["list_step_actions"]>>,
  Assert<Accepts<WorkActionPage, Results["reorder_step_actions"]>>,
  Assert<Accepts<WorkAction, Results["restore_step_action"]["action"]>>,
  Assert<Accepts<WorkLinkResult, Results["unlink_contact_from_task"]>>,
  Assert<Accepts<WorkLinkResult, Results["link_contact_to_project"]>>,
  Assert<Accepts<WorkLinkResult, Results["unlink_contact_from_project"]>>,
  Assert<Accepts<WorkLinkResult, Results["link_external_reference_to_task"]>>,
  Assert<
    Accepts<
      WorkUnlinkReferenceResult,
      Results["unlink_external_reference_from_task"]
    >
  >,
  Assert<
    Accepts<
      WorkExternalReference,
      Item<Results["list_task_external_references"]["items"]>
    >
  >,
  Assert<Accepts<WorkContactRecord, Results["update_contact"]["contact"]>>,
  Assert<Accepts<WorkContactRecord, Results["add_contact_alias"]["contact"]>>,
  Assert<
    Accepts<WorkContactRecord, Results["remove_contact_alias"]["contact"]>
  >,
  Assert<Accepts<WorkContactRecord, Results["archive_contact"]["contact"]>>,
  Assert<Accepts<WorkContactRecord, Results["restore_contact"]["contact"]>>,
  Assert<Accepts<WorkContactContext, Results["get_contact_context"]>>,
  Assert<Accepts<WorkBoardPage, Results["get_work_board"]>>,
  Assert<Accepts<WorkAgendaPage, Results["get_work_agenda"]>>,
  // WorkItemRecord is the agenda record with only the identity required; the board columns and
  // the show_work_changes card carry the same record.
  Assert<Accepts<WorkItemRecord, Item<Results["get_work_agenda"]["items"]>>>,
  Assert<
    Accepts<WorkItemRecord, Item<Results["get_work_board"]["columns"][string]>>
  >,
  Assert<
    Accepts<WorkItemRecord, Item<Results["show_work_changes"]["card"]["items"]>>
  >,
  Assert<
    Accepts<WorkSavedView, Results["create_saved_work_view"]["saved_view"]>
  >,
  Assert<
    Accepts<
      WorkSavedView,
      Item<Results["list_saved_work_views"]["saved_views"]>
    >
  >,
];

/**
 * The runtime lists the apps keep. Each list is declared `satisfies` the contract's union, so a
 * value the backend drops fails there; these assertions catch the other direction, a value the
 * backend adds that the list does not name.
 */
export type ValueSetChecks = [
  Assert<
    SameUnion<
      (typeof TASK_STATUSES)[number],
      NonNullable<Inputs["update_task"]["changes"]["status"]>
    >
  >,
  Assert<
    SameUnion<
      (typeof PROJECT_STATUSES)[number],
      NonNullable<Inputs["update_project"]["changes"]["status"]>
    >
  >,
  Assert<
    SameUnion<
      (typeof DOMAIN_ACCENTS)[number],
      NonNullable<Results["get_domain"]["domain"]["accent"]>
    >
  >,
  Assert<
    SameUnion<
      (typeof MEMORY_DOMAINS)[number],
      Item<Results["set_memory_settings"]["turning_off"]>["domain"]
    >
  >,
  Assert<
    SameUnion<
      (typeof KEY_POINT_KINDS)[number],
      Results["get_journal_entry"]["entry"]["key_points"][number]["kind"]
    >
  >,
];

/**
 * The saved view definition is read from the server with its enum fields as plain strings (the
 * output schema) and sent back from validated choices (the input schema has closed value sets),
 * so the two directions differ in the type of those fields. The key coverage is still checked, so
 * a renamed field is caught.
 */
export type SavedViewChecks = [
  Assert<
    Covers<
      WorkSavedViewDefinition,
      NonNullable<Inputs["update_saved_work_view"]["definition"]>
    >
  >,
  Assert<
    Covers<
      WorkSavedViewDefinition,
      NonNullable<Inputs["create_saved_work_view"]["definition"]>
    >
  >,
];

type Got = Results["get_task"];
/**
 * Guard against a vacuous check: each line below must fail to compile, which the expect-error
 * directive proves. If `Accepts` or `Covers` ever returned true for a mismatch, tsc would report
 * an unused directive here.
 */
// @ts-expect-error a client type that needs a field the server does not send
export type RejectsMissing = Assert<Accepts<{ nope: string }, Got>>;
// @ts-expect-error a client type that is narrower than what the server sends
export type RejectsNarrow = Assert<Accepts<{ task: { id: 1 } }, Got>>;
// @ts-expect-error a client key the server does not send (a renamed field)
export type RejectsKey = Assert<Covers<{ nope?: string }, Got>>;
// @ts-expect-error a union that lacks a value the server sends
export type RejectsUnion = Assert<SameUnion<"todo", "todo" | "done">>;
