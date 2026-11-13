import type { ToolArgs } from "../../mcp-apps/room-types";
import {
  rootFromToolResult,
  type WorkFrame,
  type WorkTransport,
} from "../transport/transport";

/** What Try again reads after a failed first result, and the notice subject that names that read. */
export type FirstRead = {
  /** The key of the heading in the shared read notice (ErrorNotice `subject`). */
  subject: string;
  read: (transport: WorkTransport) => Promise<WorkFrame>;
};

/**
 * The read behind Try again for an error result in the Work room. When the host reported the tool and its record id,
 * that very read is repeated and the heading names the Task or the Project. Otherwise the result names no record, only
 * the view of the card it landed in, so the reads that need no argument are the ones that can be repeated: the
 * Projects for a hierarchy card, the agenda for everything else. The heading names the read, so it never claims more
 * than Try again will bring back.
 */
export function firstReadFor(
  view: string | undefined,
  toolArgs?: ToolArgs,
): FirstRead {
  const { tool, id } = toolArgs ?? {};
  if (id && tool === "get_task")
    return {
      subject: "work:task",
      read: (t) =>
        t
          .getTask(id)
          .then((r) => rootFromToolResult(r) ?? { kind: "task", id }),
    };
  if (id && tool === "get_project")
    return {
      subject: "work:project",
      read: (t) =>
        t
          .getProject(id)
          .then((r) => rootFromToolResult(r) ?? { kind: "project", id }),
    };
  if (view === "hierarchy")
    return { subject: "work:hierarchy", read: (t) => t.getWorkHierarchy() };
  return {
    subject: "work",
    read: (t) =>
      t
        .getWorkAgenda({})
        .then((page) => ({ kind: "agenda", filters: {}, page })),
  };
}

/**
 * The read behind Try again for an error result in the Contacts room: the Contact when the host reported its id,
 * otherwise undefined and the room reads its list.
 */
export function contactFirstRead(toolArgs?: ToolArgs): FirstRead | undefined {
  const id = toolArgs?.id;
  if (!id || toolArgs?.tool !== "get_contact_context") return undefined;
  return {
    subject: "contacts:contact",
    read: (t) =>
      t.getContactContext(id).then((context) => ({
        kind: "contact",
        id,
        context,
      })),
  };
}
