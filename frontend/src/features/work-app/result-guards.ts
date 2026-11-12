/**
 * Runtime guards for the records a tool result opens a Work frame with. Each guard is built from the
 * shape generated out of the tool contract (`tool-shapes.generated.ts`), so the field types come
 * from the contract; the key lists below name only the fields a view cannot work without. Any
 * other field of the shape is checked when present, and extra fields are allowed.
 */
import { recordGuard, shapeAt } from "../../lib/mcp/shape";
import {
  createContactResultShape,
  getContactContextResultShape,
  getProjectResultShape,
  getTaskResultShape,
  getWorkAgendaResultShape,
  getWorkHierarchyResultShape,
  listContactsResultShape,
} from "../../lib/mcp/tool-shapes.generated";
import type {
  WorkHierarchyNode,
  WorkHierarchyTask,
  WorkItemRecord,
} from "./transport-frames";
import type {
  WorkContactRecord,
  WorkContactSummary,
  WorkJournalEntries,
  WorkProject,
  WorkProjectSummary,
  WorkTask,
  WorkTaskSummary,
} from "./transport-records";

/** A Contact record as the result carries it: the four optional profile fields may be absent. */
export type WireContactRecord = Omit<
  WorkContactRecord,
  "relationship" | "organization" | "role" | "address"
> &
  Partial<
    Pick<
      WorkContactRecord,
      "relationship" | "organization" | "role" | "address"
    >
  >;

const contextShape = getContactContextResultShape;

/** A Task as get_task returns it: the text, status, due instant and version the card shows. */
export const isWorkTask = recordGuard<WorkTask>(
  shapeAt(getTaskResultShape, "task"),
  ["id", "title", "status", "due_at", "version"],
);

/** A Project as get_project returns it: the text, status, dates and version the card shows. */
export const isWorkProject = recordGuard<WorkProject>(
  shapeAt(getProjectResultShape, "project"),
  [
    "id",
    "title",
    "status",
    "description",
    "start_date",
    "target_date",
    "version",
  ],
);

/**
 * A Contact record with every field the Contact card and editor read. The contract leaves
 * relationship, organization, role and address optional (default null), so an absent one is accepted
 * here and read as null by `withProfileDefaults`.
 */
export const isFullContactRecord = recordGuard<WireContactRecord>(
  shapeAt(contextShape, "contact"),
  [
    "id",
    "display_name",
    "email",
    "phone",
    "context_note",
    "aliases",
    "archived",
    "archived_at",
    "version",
  ],
);

/** A Contact record a tool result carries alone; the contact tools all return this record. */
export const isContactRecord = recordGuard<WorkContactRecord>(
  shapeAt(createContactResultShape, "contact"),
  ["id", "display_name"],
);

/** One row of list_contacts: identity and name. */
export const isContactSummary = recordGuard<WorkContactSummary>(
  shapeAt(listContactsResultShape, "contacts", "[]"),
  ["id", "display_name"],
);

/** A Project row of a Contact's context: identity, title and status. */
export const isProjectSummary = recordGuard<WorkProjectSummary>(
  shapeAt(contextShape, "projects", "items", "[]"),
  ["id", "title", "status"],
);

/** A Task row of a Contact's context: identity, title, status and due instant. */
export const isTaskSummary = recordGuard<WorkTaskSummary>(
  shapeAt(contextShape, "tasks", "items", "[]"),
  ["id", "title", "status", "due_at"],
);

/** The linked Journal entries part of a Contact's context: the rows, whether more exist, and readability. The rows are checked by the shape. */
export const isJournalEntries = recordGuard<WorkJournalEntries>(
  shapeAt(contextShape, "journal_entries"),
  ["items", "has_more", "readable"],
);

/** A hierarchy node with the identity, text and parent link the tree needs. */
export const isHierarchyNode = recordGuard<WorkHierarchyNode>(
  shapeAt(getWorkHierarchyResultShape, "nodes", "[]"),
  ["kind", "id", "title", "parent_id"],
);

/** A hierarchy Task with the identity, text, status, parent link and Steps the tree needs. */
export const isHierarchyTask = recordGuard<WorkHierarchyTask>(
  shapeAt(getWorkHierarchyResultShape, "tasks", "[]"),
  ["id", "parent_id", "title", "status", "steps"],
);

/** A Work record with the identity and text the views need; other fields are optional. */
export const isWorkItemRecord = recordGuard<WorkItemRecord>(
  shapeAt(getWorkAgendaResultShape, "items", "[]"),
  ["kind", "id", "title", "status"],
);
