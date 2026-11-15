/**
 * The Work reads the transport answers in part (companion-transport.ts): a Project's tasks, a Process's tasks (through
 * the hierarchy read) and the hierarchy itself. `supportsCall` and `plan` ask the same checks here, so a room is only
 * offered what a route takes.
 */
import { HostToolError } from "@/features/mcp-apps/bridge";
import { UUID, isRecord, type Args } from "./companion-plan";

/**
 * The one list_tasks the app answers: a Project's tasks, `project_id` with only paging next to it. Anything else
 * (the unsorted page, a Process, a status filter) has no route.
 */
export function isProjectTaskList(args: Args): boolean {
  return (
    typeof args.project_id === "string" &&
    UUID.test(args.project_id) &&
    Object.keys(args).every((key) =>
      ["project_id", "limit", "cursor"].includes(key),
    )
  );
}

/** The arguments get_work_hierarchy takes (contracts/mcp-tools.generated.json); anything else is refused. */
export const HIERARCHY_QUERY_KEYS = [
  "limit",
  "cursor",
  "include_tasks",
  "process_id",
];

/**
 * A hierarchy read the route takes: only its own arguments, a whole `limit` of 1 to 100, a text `cursor`, a boolean
 * `include_tasks`, and `process_id` (a uuid) only together with `include_tasks: true`, as the server insists.
 */
export function isHierarchyRead(args: Args): boolean {
  if (!Object.keys(args).every((key) => HIERARCHY_QUERY_KEYS.includes(key)))
    return false;
  const { limit, cursor, include_tasks: tasks, process_id: process } = args;
  const given = (value: unknown) => value !== undefined && value !== null;
  if (
    given(limit) &&
    !(typeof limit === "number" && Number.isInteger(limit) && limit >= 1)
  )
    return false;
  if (given(cursor) && typeof cursor !== "string") return false;
  if (given(tasks) && typeof tasks !== "boolean") return false;
  if (given(process))
    return typeof process === "string" && UUID.test(process) && tasks === true;
  return true;
}

/**
 * The one list_tasks of a Process the app answers: `process_id` with `limit` next to it. The phone has no route that
 * lists a Process's Tasks, so it asks the hierarchy for them (include_tasks with process_id) and answers one page: a
 * cursor other than null is refused, because the hierarchy's cursor pages its nodes, not its Tasks. The server has no
 * cursor for the Tasks past its cap, so the answer says `truncated` instead.
 */
export function isProcessTaskList(args: Args): boolean {
  return (
    typeof args.process_id === "string" &&
    UUID.test(args.process_id) &&
    (args.cursor === undefined || args.cursor === null) &&
    Object.keys(args).every((key) =>
      ["process_id", "limit", "cursor"].includes(key),
    )
  );
}

/**
 * A hierarchy answer as list_tasks answers a Process: its Tasks (id, title, status, version, due date), one page. The
 * server caps the Tasks of a Process and has no cursor for the rest, so `truncated` is carried through for the app to
 * say that the list is cut; `next_cursor` stays null because there is no next page to ask for.
 */
export function processTaskPage(body: Args): Args {
  if (!Array.isArray(body.tasks)) throw new HostToolError(undefined);
  const tasks = body.tasks.filter(isRecord).map((task) => ({
    id: task.id,
    title: task.title,
    status: task.status,
    version: task.version,
    due_at: task.due_at ?? null,
  }));
  return { tasks, next_cursor: null, truncated: body.truncated === true };
}
