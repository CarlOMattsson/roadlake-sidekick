import { describe, expect, it } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { fakeNative, ok } from "./helpers/fake-native";
import {
  TASK_ID,
  KEY,
  PROJECT_ID,
  DOMAIN_ID,
  PROCESS_ID,
  STEP_ID,
} from "./helpers/companion-transport-fixtures";

describe("CompanionRoomTransport idempotency", () => {
  const complete = { task_id: TASK_ID, version: 3 };

  it("sends the same key again when the same action is retried after no answer", async () => {
    let down = true;
    const native = fakeNative(() => {
      if (down) throw new Error("timeout");
      return ok({ task: { id: TASK_ID } });
    });
    const transport = new CompanionRoomTransport(native);

    await expect(
      transport.call("complete_task", complete),
    ).rejects.toBeInstanceOf(HostToolError);
    down = false;
    await transport.call("complete_task", complete);

    const [first, second] = native.requests;
    expect(first?.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(second?.idempotencyKey).toBe(first?.idempotencyKey);
  });

  it("keeps the key through a server error (5xx) and forgets it once the action is settled", async () => {
    const statuses = [503, 200, 200];
    const native = fakeNative(() => ({
      status: statuses.shift()!,
      body: { task: {} },
    }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("complete_task", complete).catch(() => undefined);
    await transport.call("complete_task", complete); // retry, succeeds
    await transport.call("complete_task", complete); // a new action: reopened and done again

    const keys = native.requests.map((request) => request.idempotencyKey);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("uses a new key for another version of the same task", async () => {
    const native = fakeNative(() => ({ status: 503, body: null }));
    const transport = new CompanionRoomTransport(native);

    await transport
      .call("complete_task", { ...complete, version: 3 })
      .catch(() => undefined);
    await transport
      .call("complete_task", { ...complete, version: 4 })
      .catch(() => undefined);

    const [first, second] = native.requests;
    expect(second?.idempotencyKey).not.toBe(first?.idempotencyKey);
  });

  it("sends the room's own key as it is, also on every retry", async () => {
    const native = fakeNative(() => ({ status: 503, body: null }));
    const transport = new CompanionRoomTransport(native);
    const args = { ...complete, idempotency_key: KEY };

    await transport.call("complete_task", args).catch(() => undefined);
    await transport.call("complete_task", args).catch(() => undefined);

    expect(native.requests.map((request) => request.idempotencyKey)).toEqual([
      KEY,
      KEY,
    ]);
  });
});

describe("CompanionRoomTransport Arbete reads", () => {
  it.each([
    [
      "get_work_hierarchy",
      {},
      { method: "GET", path: "/companion/v1/work/hierarchy" },
    ],
    [
      "get_work_hierarchy with a limit",
      { limit: 200 },
      {
        method: "GET",
        path: "/companion/v1/work/hierarchy",
        query: { limit: "200" },
      },
    ],
    [
      "get_work_hierarchy with its Tasks",
      { include_tasks: true },
      {
        method: "GET",
        path: "/companion/v1/work/hierarchy",
        query: { include_tasks: "true" },
      },
    ],
    [
      "get_work_hierarchy with a cursor",
      { limit: 50, cursor: "abc" },
      {
        method: "GET",
        path: "/companion/v1/work/hierarchy",
        query: { limit: "50", cursor: "abc" },
      },
    ],
    [
      "get_work_hierarchy with the Tasks of one Process",
      { include_tasks: true, process_id: PROCESS_ID.toUpperCase() },
      {
        method: "GET",
        path: "/companion/v1/work/hierarchy",
        query: { include_tasks: "true", process_id: PROCESS_ID },
      },
    ],
    [
      "get_project",
      { project_id: PROJECT_ID },
      { method: "GET", path: `/companion/v1/projects/${PROJECT_ID}` },
    ],
    [
      "get_domain",
      { domain_id: DOMAIN_ID },
      { method: "GET", path: `/companion/v1/domains/${DOMAIN_ID}` },
    ],
    [
      "get_process",
      { process_id: PROCESS_ID },
      { method: "GET", path: `/companion/v1/processes/${PROCESS_ID}` },
    ],
    [
      "list_tasks of a Project",
      { project_id: PROJECT_ID },
      { method: "GET", path: `/companion/v1/projects/${PROJECT_ID}/tasks` },
    ],
    [
      "list_tasks of a Project with limit and cursor",
      { project_id: PROJECT_ID, limit: 20, cursor: "abc" },
      {
        method: "GET",
        path: `/companion/v1/projects/${PROJECT_ID}/tasks`,
        query: { limit: "20", cursor: "abc" },
      },
    ],
    [
      "list_tasks of a Project with a null cursor (the first page)",
      { project_id: PROJECT_ID, limit: 20, cursor: null },
      {
        method: "GET",
        path: `/companion/v1/projects/${PROJECT_ID}/tasks`,
        query: { limit: "20" },
      },
    ],
  ])("maps %s to its one route", async (label, args, request) => {
    const native = fakeNative(() => ok({ items: [] }));
    const transport = new CompanionRoomTransport(native);
    const name = label.split(" ")[0] as string;

    const result = await transport.call(name, args);

    expect(result).toEqual({ items: [] });
    expect(native.requests).toEqual([request]);
  });

  it("answers list_tasks of a Process from the hierarchy's Tasks of that Process, as one page", async () => {
    const native = fakeNative(() =>
      ok({
        nodes: [],
        truncated: false,
        next_cursor: null,
        tasks: [
          {
            id: TASK_ID,
            parent_id: PROCESS_ID,
            title: "Pay rent",
            status: "todo",
            version: 4,
            due_at: null,
            steps: [{ id: STEP_ID, title: "Log in", status: "todo" }],
          },
        ],
      }),
    );
    const transport = new CompanionRoomTransport(native);

    const page = await transport.call("list_tasks", {
      process_id: PROCESS_ID.toUpperCase(),
      limit: 20,
      cursor: null,
    });

    expect(native.requests).toEqual([
      {
        method: "GET",
        path: "/companion/v1/work/hierarchy",
        query: { limit: "1", include_tasks: "true", process_id: PROCESS_ID },
      },
    ]);
    expect(page).toEqual({
      tasks: [
        {
          id: TASK_ID,
          title: "Pay rent",
          status: "todo",
          version: 4,
          due_at: null,
        },
      ],
      next_cursor: null,
      truncated: false,
    });
  });

  it("keeps the hierarchy's truncated flag on list_tasks of a Process, which has no cursor to follow", async () => {
    const native = fakeNative(() =>
      ok({ nodes: [], truncated: true, next_cursor: null, tasks: [] }),
    );
    const transport = new CompanionRoomTransport(native);

    const page = await transport.call("list_tasks", { process_id: PROCESS_ID });

    expect(page).toEqual({ tasks: [], next_cursor: null, truncated: true });
  });

  it("fails list_tasks of a Process when the answer carries no Tasks", async () => {
    const transport = new CompanionRoomTransport(
      fakeNative(() => ok({ nodes: [] })),
    );

    await expect(
      transport.call("list_tasks", { process_id: PROCESS_ID }),
    ).rejects.toBeInstanceOf(HostToolError);
  });

  it("writes the path with a lower-case id, as the backend's route takes only that", async () => {
    const native = fakeNative(() => ok({ project: {} }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("get_project", {
      project_id: PROJECT_ID.toUpperCase(),
    });

    expect(native.requests[0]?.path).toBe(
      `/companion/v1/projects/${PROJECT_ID}`,
    );
  });

  it.each([
    ["another key on the hierarchy", "get_work_hierarchy", { status: "todo" }],
    [
      "a non-boolean include_tasks on the hierarchy",
      "get_work_hierarchy",
      { include_tasks: "yes" },
    ],
    [
      "a process_id without include_tasks on the hierarchy",
      "get_work_hierarchy",
      { process_id: PROCESS_ID },
    ],
    [
      "a process_id that is not a uuid on the hierarchy",
      "get_work_hierarchy",
      { include_tasks: true, process_id: "../x" },
    ],
    [
      "an object as the hierarchy cursor",
      "get_work_hierarchy",
      { cursor: { a: 1 } },
    ],
    [
      "an object as the hierarchy limit",
      "get_work_hierarchy",
      { limit: { a: 1 } },
    ],
    ["a project id that is not a uuid", "get_project", { project_id: "../x" }],
    ["a missing project id", "get_project", {}],
    [
      "an extra get_project argument",
      "get_project",
      { project_id: PROJECT_ID, url: "https://x" },
    ],
    [
      "a path in the domain id",
      "get_domain",
      { domain_id: `${DOMAIN_ID}/../x` },
    ],
    [
      "an extra get_domain argument",
      "get_domain",
      { domain_id: DOMAIN_ID, include_archived: true },
    ],
    ["a process id that is not a uuid", "get_process", { process_id: "x" }],
    [
      "an extra get_process argument",
      "get_process",
      { process_id: PROCESS_ID, url: "https://x" },
    ],
    [
      "a step id that is not a uuid on the Step complete",
      "complete_task_step",
      { step_id: "../x", version: 1, idempotency_key: KEY },
    ],
    [
      "a missing Step version",
      "complete_task_step",
      { step_id: STEP_ID, idempotency_key: KEY },
    ],
    [
      "a task_id on a Step write (the Step is named step_id)",
      "complete_task_step",
      { task_id: TASK_ID, version: 1, idempotency_key: KEY },
    ],
    [
      "an extra complete_task_step argument",
      "complete_task_step",
      { step_id: STEP_ID, version: 1, idempotency_key: KEY, note: "x" },
    ],
    [
      "a too short key on the Step reopen",
      "update_task_step",
      {
        step_id: STEP_ID,
        version: 1,
        idempotency_key: "k",
        changes: { status: "todo" },
      },
    ],
  ])(
    "refuses %s as a validation error and sends nothing",
    async (_label, name, args) => {
      const native = fakeNative(() => ok({}));
      const transport = new CompanionRoomTransport(native);

      const error = await transport.call(name, args).catch((e: unknown) => e);

      expect(error).toBeInstanceOf(HostToolError);
      expect((error as HostToolError).code).toBe("validation_error");
      expect(native.requests).toEqual([]);
    },
  );

  it.each([
    ["no project_id (the unsorted page or all tasks)", {}],
    ["unsorted", { unsorted: true, limit: 20 }],
    ["unsorted with a project", { project_id: PROJECT_ID, unsorted: true }],
    [
      "a Process with a cursor (the hierarchy's cursor pages nodes)",
      { process_id: PROCESS_ID, cursor: "abc" },
    ],
    [
      "a Process with a status filter",
      { process_id: PROCESS_ID, status: "todo" },
    ],
    [
      "a Process beside the Project",
      { project_id: PROJECT_ID, process_id: PROCESS_ID },
    ],
    ["a status filter", { project_id: PROJECT_ID, status: "todo" }],
    ["a status filter alone", { status: "todo" }],
    ["a project id that is not a uuid", { project_id: "../x" }],
  ])(
    "refuses list_tasks with %s as 'not in the app' and sends nothing",
    async (_label, args) => {
      const native = fakeNative(() => ok({}));
      const transport = new CompanionRoomTransport(native);

      const error = await transport
        .call("list_tasks", args)
        .catch((e: unknown) => e);

      expect(error).toBeInstanceOf(NotInAppError);
      expect((error as HostToolError).code).toBe("not_in_app");
      expect(native.requests).toEqual([]);
    },
  );
});

describe("CompanionRoomTransport offline copies of Arbete", () => {
  const at = Date.UTC(2026, 10, 11, 13, 2);

  it("tells when an Agenda page or a Task detail came from the offline copy", async () => {
    const native = fakeNative((request) =>
      request.path.endsWith("/work/agenda")
        ? { status: 200, body: { items: [], next_cursor: null }, cachedAt: at }
        : ok({ task: { id: TASK_ID } }),
    );
    const transport = new CompanionRoomTransport(native);
    const agenda = await transport.call<object>("get_work_agenda", {
      sort: "due_asc",
    });
    const fresh = await transport.call<object>("get_task", {
      task_id: TASK_ID,
    });
    expect(transport.offline.readAt(agenda)).toBe(at);
    expect(transport.offline.readAt(fresh)).toBeUndefined();
  });

  it("names the Tasks whose completion waits in the outbox, in lower case", async () => {
    const native = fakeNative(() => ok({}));
    native.completions.set(TASK_ID.toUpperCase(), at);
    const transport = new CompanionRoomTransport(native);
    expect(await transport.offline.queuedCompletions?.()).toEqual(
      new Set([TASK_ID]),
    );
    native.completions.clear();
    expect(await transport.offline.queuedCompletions?.()).toEqual(new Set());
  });

  it("names none when the phone build has no completions or cannot be asked", async () => {
    const older = fakeNative(() => ok({}));
    older.queuedWrites = () => Promise.resolve({ purchases: [], adds: [] });
    expect(
      await new CompanionRoomTransport(older).offline.queuedCompletions?.(),
    ).toEqual(new Set());
    const failing = fakeNative(() => ok({}));
    failing.queuedWrites = () => Promise.reject(new Error("closed"));
    expect(
      await new CompanionRoomTransport(failing).offline.queuedCompletions?.(),
    ).toEqual(new Set());
  });
});
