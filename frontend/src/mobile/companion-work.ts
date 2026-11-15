/**
 * The Work room's writes over the companion routes (ADR-005, amendment 2026-11-15: writing from the app). Each tool
 * the room asks for maps, from this CLOSED list, to one named route; the answer is the tool's own structuredContent
 * (`{ task }`, `{ project }`), so the room cannot tell the difference. No generic execute, no path from the caller, no
 * argument outside what the route takes.
 *
 *   create_task    -> POST /companion/v1/tasks                       (title, due_at, description, priority, one place)
 *   update_task    -> POST /companion/v1/tasks/{task_id}/update      ({ version } and the edit fields of TASK_EDIT_KEYS)
 *   update_project -> POST /companion/v1/projects/{project_id}/update ({ version } and PROJECT_EDIT_KEYS)
 *
 * The tick and its undo keep their own routes (companion-transport.ts). What the routes do not take (tags, recurrence,
 * waiting, estimates, a Project's domain or tags) is answered no by `supportsCall`, so the room offers no control for
 * it. Every write sends its key in the Idempotency-Key header; the room's retry of the same action reuses it.
 */
import {
  isRecord,
  type Args,
  type PlanHelpers,
  type Planned,
  type Queueable,
} from "./companion-plan";

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const WORK_WRITE_ROUTES = {
  create_task: { method: "POST", path: "/companion/v1/tasks" },
  update_task: {
    method: "POST",
    path: "/companion/v1/tasks/{task_id}/update",
  },
  update_project: {
    method: "POST",
    path: "/companion/v1/projects/{project_id}/update",
  },
} as const;

/** The tool names this planner adds to the list (update_task is answered by the transport already, for the tick). */
export const WORK_WRITE_TOOLS = ["create_task", "update_project"] as const;

/** The Task fields the edit route takes; a change outside them is not answered. */
export const TASK_EDIT_KEYS = [
  "title",
  "description",
  "due_at",
  "project_id",
  "process_id",
  "domain_id",
  "priority",
] as const;

/** The Project fields the edit route takes; tags, the definition of done and the domain stay with Claude. */
export const PROJECT_EDIT_KEYS = [
  "title",
  "status",
  "description",
  "start_date",
  "target_date",
] as const;

/** The place keys a new Task names at most one of (the use case insists). */
const CREATE_KEYS = [
  "title",
  "due_at",
  "description",
  "priority",
  "project_id",
  "process_id",
  "domain_id",
  "idempotency_key",
] as const;

/** A change set the route takes: at least one change, and only keys in `allowed`. */
function isEditOf(changes: unknown, allowed: readonly string[]): boolean {
  if (!isRecord(changes)) return false;
  const keys = Object.keys(changes);
  return keys.length > 0 && keys.every((key) => allowed.includes(key));
}

/** The one update_task the edit route answers besides the tick: only the fields of TASK_EDIT_KEYS. */
export function isTaskEdit(changes: unknown): boolean {
  return isEditOf(changes, TASK_EDIT_KEYS);
}

/** The update_project the edit route answers: only the fields of PROJECT_EDIT_KEYS. */
export function isProjectEdit(changes: unknown): boolean {
  return isEditOf(changes, PROJECT_EDIT_KEYS);
}

/** The one change update_task is answered for: the tick, `{ status: "completed" }` and nothing else. */
export function isCompletingChange(changes: unknown): boolean {
  return (
    isRecord(changes) &&
    Object.keys(changes).length === 1 &&
    changes.status === "completed"
  );
}

/**
 * The other change update_task is answered for: back to open, `{ status: "todo" }` and nothing else. The backend's
 * reopen route sets exactly "todo" and only on a completed Task, so no other status is ever answered.
 */
export function isReopeningChange(changes: unknown): boolean {
  return (
    isRecord(changes) &&
    Object.keys(changes).length === 1 &&
    changes.status === "todo"
  );
}

/** The planned call for a Work write tool, or undefined when the name is not one of them (or update_task's tick). */
export function planWorkWrite(
  name: string,
  args: Args,
  h: PlanHelpers,
): Planned | undefined {
  /**
   * A write: the signature is the action itself, so a retry of the same action sends the same key. Without a network
   * the phone's outbox keeps it (`queue`) and sends it with that key.
   */
  const write = (
    path: string,
    body: Args,
    record: { subjectId?: string; version?: number },
  ): Planned => {
    const signature = JSON.stringify([name, path, body]);
    const queue: Queueable = {
      kind: "record",
      write: name as "create_task" | "update_task" | "update_project",
      ...record,
      body,
    };
    return {
      request: {
        method: "POST",
        path,
        body,
        idempotencyKey: h.keyOf(args.idempotency_key, signature),
      },
      signature,
      queue,
    };
  };
  const text = (value: unknown): string =>
    typeof value === "string" ? value : h.invalid();
  const id = (value: unknown): string => h.uuidOf(value);
  /** `kinds` converts a given field; null is kept (it clears) only for the keys in `nullable`. */
  const fields = (
    source: Args,
    keys: readonly string[],
    kinds: Record<string, (value: unknown) => unknown>,
    nullable: readonly string[],
  ): Args => {
    const body: Args = {};
    for (const key of keys) {
      const value = source[key];
      if (value === undefined) continue;
      if (value === null) {
        if (!nullable.includes(key)) h.invalid();
        body[key] = null;
        continue;
      }
      body[key] = kinds[key]?.(value) ?? value;
    }
    return body;
  };

  switch (name) {
    case "create_task": {
      h.onlyKeys(args, CREATE_KEYS);
      const body = fields(
        args,
        CREATE_KEYS.filter((key) => key !== "idempotency_key"),
        {
          title: text,
          due_at: text,
          description: text,
          priority: text,
          project_id: id,
          process_id: id,
          domain_id: id,
        },
        // A form that leaves a field empty may send null for it; the route's own default is the same.
        ["due_at", "description", "project_id", "process_id", "domain_id"],
      );
      // A null is "not given" on a new Task, so it is dropped, not sent.
      for (const key of Object.keys(body))
        if (body[key] === null) delete body[key];
      if (typeof body.title !== "string") return h.invalid();
      return write("/companion/v1/tasks", body, {});
    }
    case "update_task": {
      h.onlyKeys(args, ["task_id", "version", "idempotency_key", "changes"]);
      if (!isTaskEdit(args.changes)) return undefined;
      const taskId = h.uuidOf(args.task_id);
      const version = h.versionOf(args.version);
      const body = fields(
        args.changes as Args,
        TASK_EDIT_KEYS,
        {
          title: text,
          description: text,
          due_at: text,
          priority: text,
          project_id: id,
          process_id: id,
          domain_id: id,
        },
        ["description", "due_at", "project_id", "process_id", "domain_id"],
      );
      return write(
        `/companion/v1/tasks/${taskId}/update`,
        { version, ...body },
        { subjectId: taskId, version },
      );
    }
    case "update_project": {
      h.onlyKeys(args, ["project_id", "version", "idempotency_key", "changes"]);
      if (!isProjectEdit(args.changes)) return h.invalid();
      const projectId = h.uuidOf(args.project_id);
      const version = h.versionOf(args.version);
      const body = fields(
        args.changes as Args,
        PROJECT_EDIT_KEYS,
        {
          title: text,
          status: text,
          description: text,
          start_date: text,
          target_date: text,
        },
        ["description", "start_date", "target_date"],
      );
      return write(
        `/companion/v1/projects/${projectId}/update`,
        { version, ...body },
        { subjectId: projectId, version },
      );
    }
    default:
      return undefined;
  }
}
