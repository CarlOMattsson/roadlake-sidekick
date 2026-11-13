/**
 * The Work App command contract: every typed read and write a view can make. The MCP adapter
 * (work-transport.ts) maps them to tools/call and reads structuredContent.
 */
import type { OfflineSupport } from "../../mcp-apps/room-types";
import type { ToolSupport } from "../../mcp-apps/tool-support";
import type { ReadTags } from "../../mcp-apps/ui/tag-vocabulary";
import type {
  WorkFilters,
  WorkAgendaPage,
  WorkBoardPage,
  WorkHierarchyFrame,
} from "./transport-frames";
import type {
  TaskStatusValue,
  WorkAction,
  WorkActionPage,
  WorkBoardPlacement,
  WorkBoardPlacementItem,
  WorkContactChanges,
  WorkContactContext,
  WorkContactCreate,
  WorkContactPage,
  WorkContactRecord,
  WorkContactSummary,
  WorkDomain,
  WorkDomainRecord,
  WorkExternalReference,
  WorkExternalReferencePage,
  WorkLinkResult,
  WorkOrderItem,
  WorkProcessRecord,
  WorkProject,
  WorkProjectChanges,
  WorkRescheduleResult,
  WorkSavedView,
  WorkSavedViewDefinition,
  WorkStep,
  WorkStepPage,
  WorkTask,
  WorkTaskChanges,
  WorkTaskCreate,
  WorkTaskSummaryPage,
  WorkUnlinkReferenceResult,
  WorkUnsortedPage,
} from "./transport-records";

export type WorkTransport = ToolSupport & {
  /**
   * The phone's offline help (the mobile app only): when a read is its offline copy, and which Tasks wait in its
   * outbox to be sent as done. Absent in Claude.
   */
  offline?: Pick<
    OfflineSupport,
    "readAt" | "queuedCompletions" | "onQueueChanged"
  >;
  getTask: (taskId: string) => Promise<{ task: WorkTask }>;
  getProject: (projectId: string) => Promise<{ project: WorkProject }>;
  /** Writes the given changes against `version`; resolves the Project as stored, with its new version. */
  updateProject: (
    projectId: string,
    version: number,
    changes: WorkProjectChanges,
    idempotencyKey: string,
  ) => Promise<{ project: WorkProject }>;
  /** Tasks of one Project, one page per call; omit the cursor for the first page. */
  listProjectTasks: (
    projectId: string,
    cursor?: string | null,
  ) => Promise<WorkTaskSummaryPage>;
  /** Tasks of one Process, one page per call; omit the cursor for the first page. */
  listProcessTasks: (
    processId: string,
    cursor?: string | null,
  ) => Promise<WorkTaskSummaryPage>;
  /** Writes the given changes against `version`; resolves the Task as stored, with its new version. */
  updateTask: (
    taskId: string,
    version: number,
    changes: WorkTaskChanges,
    idempotencyKey: string,
  ) => Promise<{ task: WorkTask }>;
  /**
   * Moves 1 to 20 Tasks to a new due date in one call (`reschedule_tasks`). `when` is "tomorrow", "next_week",
   * a YYYY-MM-DD date or "clear". The whole call fails if one version is stale.
   */
  rescheduleTasks: (
    items: { taskId: string; version: number; when: "tomorrow" }[],
    idempotencyKey: string,
  ) => Promise<WorkRescheduleResult>;
  /**
   * Tasks with no Domain, Project or Process, one page per call; omit the cursor for the first page.
   * The limit defaults to 25 (the sorting view); the To sort row counts with 100, the server's maximum.
   */
  listUnsortedTasks: (
    cursor?: string | null,
    limit?: number,
  ) => Promise<WorkUnsortedPage>;
  /** The Domains a Task can be sorted into (list_domains, first page; archived Domains are not listed). */
  listDomains: () => Promise<WorkDomain[]>;
  /** One page of a Task's Steps (100); pass the previous page's next_cursor for the next one. */
  listTaskSteps: (taskId: string, cursor?: string) => Promise<WorkStepPage>;
  /** Creates a Task, in a Project or Process when the body names one; resolves the Task as stored. The key makes a retry replay the result. */
  createTask: (
    task: WorkTaskCreate,
    idempotencyKey: string,
  ) => Promise<{ task: WorkTask }>;
  /** Appends a Step to the Task; resolves the Step as stored, with its version. */
  createTaskStep: (
    taskId: string,
    title: string,
    idempotencyKey: string,
  ) => Promise<{ step: WorkStep }>;
  completeTaskStep: (
    stepId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ step: WorkStep }>;
  updateTaskStep: (
    stepId: string,
    version: number,
    changes: { status: TaskStatusValue },
    idempotencyKey: string,
  ) => Promise<{ step: WorkStep }>;
  listTaskContacts: (
    taskId: string,
    cursor?: string | null,
  ) => Promise<WorkContactPage>;
  /** Contacts whose name or alias matches q, one page per call; omit the cursor for the first page. */
  searchContacts: (
    q: string,
    cursor?: string | null,
  ) => Promise<WorkContactPage>;
  /**
   * The Contact list, one page per call; omit the cursor for the first page. An empty q lists every Contact;
   * `tags` keeps the Contacts that carry every one of them.
   */
  listContacts: (
    options: { q: string; includeArchived: boolean; tags?: string[] },
    cursor?: string | null,
  ) => Promise<{ items: WorkContactSummary[]; next_cursor: string | null }>;
  /** Creates a Contact; resolves it as stored. The key makes a retry replay the result. */
  createContact: (
    contact: WorkContactCreate,
    idempotencyKey: string,
  ) => Promise<{ contact: WorkContactRecord }>;
  linkContactToTask: (
    taskId: string,
    contactId: string,
    idempotencyKey: string,
  ) => Promise<WorkLinkResult>;
  unlinkContactFromTask: (
    taskId: string,
    contactId: string,
    idempotencyKey: string,
  ) => Promise<WorkLinkResult>;
  /**
   * Moves the Task to the trash at `version` (move_to_trash, kind "task"). The answer carries the trash record's
   * version, which `restoreTask` needs for Undo. The view offers this only when the host answers both tools.
   */
  trashTask: (
    taskId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ version: number }>;
  /** Takes the Task back out of the trash (restore_from_trash) at the trash version `trashTask` answered with. */
  restoreTask: (
    taskId: string,
    trashVersion: number,
    idempotencyKey: string,
  ) => Promise<unknown>;
  /** taskCursor pages the contact's tasks; omit it for the first page. */
  getContactContext: (
    contactId: string,
    taskCursor?: string | null,
  ) => Promise<WorkContactContext>;
  /** The first page of the owner's tag vocabulary (list_tags); absent where the host has no such call. */
  listTags?: ReadTags;
  /** Writes the given changes against `expectedVersion`; resolves the Contact as stored. */
  updateContact: (
    contactId: string,
    expectedVersion: number,
    changes: WorkContactChanges,
    idempotencyKey: string,
  ) => Promise<{ contact: WorkContactRecord }>;
  /** Adds an alias to the Contact against `expectedVersion`; resolves the Contact as stored. */
  addContactAlias: (
    contactId: string,
    expectedVersion: number,
    value: string,
    idempotencyKey: string,
  ) => Promise<{ contact: WorkContactRecord }>;
  /** Removes one alias of the Contact against `expectedVersion`; resolves the Contact as stored. */
  removeContactAlias: (
    contactId: string,
    aliasId: string,
    expectedVersion: number,
    idempotencyKey: string,
  ) => Promise<{ contact: WorkContactRecord }>;
  /** Archives or restores the Contact against `expectedVersion`; resolves the Contact as stored. */
  archiveContact: (
    contactId: string,
    expectedVersion: number,
    idempotencyKey: string,
  ) => Promise<{ contact: WorkContactRecord }>;
  restoreContact: (
    contactId: string,
    expectedVersion: number,
    idempotencyKey: string,
  ) => Promise<{ contact: WorkContactRecord }>;
  /**
   * Sets the manual order of one complete Task status column. `items` lists every active Task in the
   * column exactly once, in the new order, with the version the board showed. The key makes a retry
   * replay the result.
   */
  reorderBoardColumn: (
    status: TaskStatusValue,
    items: WorkBoardPlacementItem[],
    idempotencyKey: string,
  ) => Promise<{ items: WorkBoardPlacement[] }>;
  /** One board page with the given filters; omit the cursor for the first page. */
  getWorkBoard: (
    filters: WorkFilters,
    cursor?: string | null,
  ) => Promise<WorkBoardPage>;
  /** One agenda page with the given filters; omit the cursor for the first page. */
  getWorkAgenda: (
    filters: WorkFilters,
    cursor?: string | null,
  ) => Promise<WorkAgendaPage>;
  /**
   * One page of the Work hierarchy as a frame (get_work_hierarchy); resolves a hierarchy frame or rejects. With
   * `includeTasks` the frame carries the active Tasks under its Projects and Processes (the Projects tab's counts).
   */
  getWorkHierarchy: (options?: {
    includeTasks?: boolean;
    /** The frame's `next_cursor`: reads the next page of nodes (and the Tasks under them) instead of the first. */
    cursor?: string;
  }) => Promise<WorkHierarchyFrame>;
  /** Archives a Step against `version`; resolves the Step as stored. Nothing is deleted. */
  archiveTaskStep: (
    stepId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ step: WorkStep }>;
  /** Restores an archived Step against `version`; resolves the Step as stored. */
  restoreTaskStep: (
    stepId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ step: WorkStep }>;
  /**
   * Sets the order of the Task's Steps. `items` lists every active Step exactly once, in the new
   * order, with the version the view holds; resolves the Steps as stored, in that order.
   */
  reorderTaskSteps: (
    taskId: string,
    items: WorkOrderItem[],
    idempotencyKey: string,
  ) => Promise<WorkStepPage>;
  /** The active Actions of one Step, in display order. */
  listStepActions: (stepId: string) => Promise<WorkActionPage>;
  archiveStepAction: (
    actionId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ action: WorkAction }>;
  restoreStepAction: (
    actionId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ action: WorkAction }>;
  /** Same contract as reorderTaskSteps, for the Actions of one Step. */
  reorderStepActions: (
    stepId: string,
    items: WorkOrderItem[],
    idempotencyKey: string,
  ) => Promise<WorkActionPage>;
  /** The owner's saved Work views; archived ones only when `includeArchived`. */
  listSavedWorkViews: (includeArchived: boolean) => Promise<WorkSavedView[]>;
  createSavedWorkView: (
    name: string,
    definition: WorkSavedViewDefinition,
    idempotencyKey: string,
  ) => Promise<{ saved_view: WorkSavedView }>;
  /** Renames the view (and/or replaces its filters) against `version`. */
  updateSavedWorkView: (
    viewId: string,
    version: number,
    changes: { name?: string; definition?: WorkSavedViewDefinition },
    idempotencyKey: string,
  ) => Promise<{ saved_view: WorkSavedView }>;
  archiveSavedWorkView: (
    viewId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ saved_view: WorkSavedView }>;
  restoreSavedWorkView: (
    viewId: string,
    version: number,
    idempotencyKey: string,
  ) => Promise<{ saved_view: WorkSavedView }>;
  linkContactToProject: (
    contactId: string,
    projectId: string,
    idempotencyKey: string,
  ) => Promise<WorkLinkResult>;
  unlinkContactFromProject: (
    contactId: string,
    projectId: string,
    idempotencyKey: string,
  ) => Promise<WorkLinkResult>;
  /** The external pointers on a Task, one page per call; omit the cursor for the first page. */
  listTaskExternalReferences: (
    taskId: string,
    cursor?: string | null,
  ) => Promise<WorkExternalReferencePage>;
  /** Removes the pointer from the Task; the mail, event or document itself is never touched. */
  unlinkExternalReferenceFromTask: (
    taskId: string,
    referenceId: string,
    idempotencyKey: string,
  ) => Promise<WorkUnlinkReferenceResult>;
  /** Links the pointer again from the snapshot the view holds (the undo of an unlink). */
  linkExternalReferenceToTask: (
    taskId: string,
    reference: WorkExternalReference,
    idempotencyKey: string,
  ) => Promise<WorkLinkResult>;
  getDomain: (domainId: string) => Promise<{ domain: WorkDomainRecord }>;
  getProcess: (processId: string) => Promise<{ process: WorkProcessRecord }>;
};
