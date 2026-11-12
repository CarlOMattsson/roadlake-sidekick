import { describe, expect, it } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  COMPANION_ROUTES,
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { fakeNative, ok } from "./helpers/fake-native";
import { TASK_ID, KEY } from "./helpers/companion-transport-fixtures";

describe("CompanionRoomTransport mapping", () => {
  it("maps get_work_agenda to GET /companion/v1/work/agenda with the arguments as the query", async () => {
    const native = fakeNative(() => ok({ items: [], next_cursor: null }));
    const transport = new CompanionRoomTransport(native);

    const result = await transport.call("get_work_agenda", {
      limit: 25,
      cursor: null,
      q: "offert",
      tags: ["a", "b"],
      include_undated: false,
    });

    expect(result).toEqual({ items: [], next_cursor: null });
    expect(native.requests).toEqual([
      {
        method: "GET",
        path: "/companion/v1/work/agenda",
        query: {
          limit: "25",
          q: "offert",
          tags: ["a", "b"],
          include_undated: "false",
        },
      },
    ]);
  });

  it("maps get_task to GET /companion/v1/tasks/{task_id}", async () => {
    const native = fakeNative(() => ok({ task: { id: TASK_ID } }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("get_task", { task_id: TASK_ID });

    expect(native.requests).toEqual([
      { method: "GET", path: `/companion/v1/tasks/${TASK_ID}` },
    ]);
  });

  it("maps complete_task to POST .../complete with version in the body and the Idempotency-Key", async () => {
    const native = fakeNative(() => ok({ task: { id: TASK_ID, version: 4 } }));
    const transport = new CompanionRoomTransport(native);

    const result = await transport.call("complete_task", {
      task_id: TASK_ID,
      version: 3,
      idempotency_key: KEY,
    });

    expect(result).toEqual({ task: { id: TASK_ID, version: 4 } });
    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/tasks/${TASK_ID}/complete`,
        body: { version: 3 },
        idempotencyKey: KEY,
      },
    ]);
    expect(COMPANION_ROUTES.complete_task.method).toBe("POST");
  });

  it("answers the Agenda's tick (update_task to completed) with the complete route", async () => {
    const native = fakeNative(() => ok({ task: { id: TASK_ID, version: 2 } }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("update_task", {
      task_id: TASK_ID,
      version: 1,
      idempotency_key: KEY,
      changes: { status: "completed" },
    });

    expect(native.requests[0]).toMatchObject({
      method: "POST",
      path: `/companion/v1/tasks/${TASK_ID}/complete`,
      body: { version: 1 },
      idempotencyKey: KEY,
    });
  });

  it("answers update_task back to todo (Ångra, Återöppna) with the reopen route and its version and key", async () => {
    const native = fakeNative(() => ok({ task: { id: TASK_ID, version: 3 } }));
    const transport = new CompanionRoomTransport(native);

    const result = await transport.call("update_task", {
      task_id: TASK_ID,
      version: 2,
      idempotency_key: KEY,
      changes: { status: "todo" },
    });

    expect(result).toEqual({ task: { id: TASK_ID, version: 3 } });
    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/tasks/${TASK_ID}/reopen`,
        body: { version: 2 },
        idempotencyKey: KEY,
      },
    ]);
    expect(COMPANION_ROUTES.reopen_task.path).toBe(
      "/companion/v1/tasks/{task_id}/reopen",
    );
  });

  it.each([
    ["list_task_steps", "steps", { limit: 100 }, { limit: "100" }],
    [
      "list_task_steps",
      "steps",
      { limit: 100, cursor: "page-2" },
      { limit: "100", cursor: "page-2" },
    ],
    [
      "list_task_contacts",
      "contacts",
      { limit: 20, cursor: null },
      { limit: "20" },
    ],
    [
      "list_task_external_references",
      "external-references",
      { limit: 25, cursor: "abc" },
      { limit: "25", cursor: "abc" },
    ],
  ])(
    "maps %s to GET .../%s with the arguments as the query",
    async (name, tail, extra, query) => {
      const native = fakeNative(() => ok({ items: [], next_cursor: null }));
      const transport = new CompanionRoomTransport(native);

      const result = await transport.call(name, { task_id: TASK_ID, ...extra });

      expect(result).toEqual({ items: [], next_cursor: null });
      expect(native.requests).toEqual([
        {
          method: "GET",
          path: `/companion/v1/tasks/${TASK_ID}/${tail}`,
          query,
        },
      ]);
    },
  );

  it("sends a task sub-list without a query when only the task is named", async () => {
    const native = fakeNative(() => ok({ steps: [] }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("list_task_steps", { task_id: TASK_ID });

    expect(native.requests).toEqual([
      { method: "GET", path: `/companion/v1/tasks/${TASK_ID}/steps` },
    ]);
  });

  it.each([
    ["an unknown tool", "list_contacts", {}],
    ["a tool that writes elsewhere", "create_task", { title: "x" }],
    [
      "update_task with another status",
      "update_task",
      {
        task_id: TASK_ID,
        version: 1,
        idempotency_key: KEY,
        changes: { status: "in_progress" },
      },
    ],
    [
      "update_task back to todo with more than the status",
      "update_task",
      {
        task_id: TASK_ID,
        version: 1,
        idempotency_key: KEY,
        changes: { status: "todo", title: "x" },
      },
    ],
    [
      "update_task with more than the status",
      "update_task",
      {
        task_id: TASK_ID,
        version: 1,
        idempotency_key: KEY,
        changes: { status: "completed", title: "x" },
      },
    ],
    [
      "a name that only looks like ours",
      "mcp__sidekick__get_task",
      { task_id: TASK_ID },
    ],
    ["a prototype name", "constructor", {}],
  ])(
    "refuses %s with a safe error and sends nothing",
    async (_label, name, args) => {
      const native = fakeNative(() => ok({}));
      const transport = new CompanionRoomTransport(native);

      const error = await transport.call(name, args).catch((e: unknown) => e);

      expect(error).toBeInstanceOf(NotInAppError);
      expect(error).toBeInstanceOf(HostToolError);
      expect((error as HostToolError).code).toBe("not_in_app");
      expect((error as Error).message).toBe("Not available in the app yet");
      expect(native.requests).toEqual([]);
    },
  );

  it.each([
    ["a task id that is not a uuid", "get_task", { task_id: "../../api/v1/x" }],
    ["a path in the task id", "get_task", { task_id: `${TASK_ID}/../x` }],
    [
      "an extra get_task argument",
      "get_task",
      { task_id: TASK_ID, url: "https://x" },
    ],
    [
      "an unknown agenda argument",
      "get_work_agenda",
      { limit: 5, project_id: TASK_ID },
    ],
    [
      "an object as a cursor on list_task_steps",
      "list_task_steps",
      { task_id: TASK_ID, cursor: { a: 1 } },
    ],
    [
      "an unknown list_task_contacts argument",
      "list_task_contacts",
      { task_id: TASK_ID, url: "https://x" },
    ],
    [
      "a task id that is not a uuid on list_task_external_references",
      "list_task_external_references",
      { task_id: "../x", limit: 5 },
    ],
    [
      "an object as a cursor",
      "list_task_contacts",
      { task_id: TASK_ID, cursor: { a: 1 } },
    ],
    ["an object as an agenda value", "get_work_agenda", { q: { a: 1 } }],
    [
      "a missing version",
      "complete_task",
      { task_id: TASK_ID, idempotency_key: KEY },
    ],
    [
      "a fractional version",
      "complete_task",
      { task_id: TASK_ID, version: 1.5, idempotency_key: KEY },
    ],
    [
      "a too short key",
      "complete_task",
      { task_id: TASK_ID, version: 1, idempotency_key: "k" },
    ],
  ])(
    "refuses %s as a validation error and sends nothing",
    async (_label, name, args) => {
      const native = fakeNative(() => ok({}));
      const transport = new CompanionRoomTransport(native);

      const error = await transport.call(name, args).catch((e: unknown) => e);

      expect((error as HostToolError).code).toBe("validation_error");
      expect(native.requests).toEqual([]);
    },
  );

  it("is always fullscreen and has no model to tell", async () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    await expect(transport.requestDisplayMode("inline")).resolves.toBe(
      "fullscreen",
    );
    await expect(
      transport.updateModelContext("Visar Arbete"),
    ).resolves.toBeUndefined();
  });

  it("says which tools it answers: its closed list, and nothing outside it", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    for (const name of [
      "get_work_agenda",
      "get_task",
      "complete_task",
      "update_task",
      "list_task_steps",
    ])
      expect(transport.supportsTool(name)).toBe(true);
    // The menu items of the Work room whose routes the companion does not have.
    for (const name of [
      "list_saved_work_views",
      "archive_saved_work_view",
      "get_control_overview",
      "delete_task",
    ])
      expect(transport.supportsTool(name)).toBe(false);
  });

  it("answers update_task for the completing change, and for todo only from a completed Task", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    expect(
      transport.supportsCall("update_task", {
        changes: { status: "completed" },
      }),
    ).toBe(true);
    // Reopen sets exactly "todo" and only on a completed Task: the asker must name it.
    expect(
      transport.supportsCall("update_task", {
        changes: { status: "todo" },
        from_status: "completed",
      }),
    ).toBe(true);
    for (const from_status of [undefined, "todo", "in_progress", "blocked"])
      expect(
        transport.supportsCall("update_task", {
          changes: { status: "todo" },
          from_status,
        }),
      ).toBe(false);
    for (const status of ["in_progress", "blocked", "cancelled"])
      expect(
        transport.supportsCall("update_task", {
          changes: { status },
          from_status: "completed",
        }),
      ).toBe(false);
    for (const changes of [
      { status: "todo" },
      { status: "in_progress" },
      { status: "todo", title: "x" },
      { due_at: null },
      { title: "x" },
      { status: "completed", title: "x" },
      {},
      undefined,
    ])
      expect(transport.supportsCall("update_task", { changes })).toBe(false);
    expect(transport.supportsCall("update_task", {})).toBe(false);
    expect(transport.supportsCall("complete_task", {})).toBe(true);
    expect(transport.supportsCall("create_task", {})).toBe(false);
  });

  it("works when a room takes `call` out of the object", async () => {
    const native = fakeNative(() => ok({ items: [] }));
    const { call } = new CompanionRoomTransport(native);

    await call("get_work_agenda", {});

    expect(native.requests).toHaveLength(1);
  });
});

describe("CompanionRoomTransport answers", () => {
  it.each([
    [401, undefined, "unauthorized"],
    [403, undefined, "forbidden"],
    [404, undefined, "not_found"],
    [409, undefined, "conflict"],
    [422, undefined, "validation_error"],
    [405, undefined, "method_not_allowed"],
    [400, { code: "bad_request" }, "bad_request"],
    [409, { code: "conflict" }, "conflict"],
    [403, { code: "forbidden" }, "forbidden"],
    [500, undefined, undefined],
    [500, { code: "Some free text!" }, undefined],
  ])(
    "turns HTTP %i %j into HostToolError code %j",
    async (status, body, code) => {
      const native = fakeNative(() => ({ status, body }));
      const transport = new CompanionRoomTransport(native);

      const error = await transport
        .call("get_task", { task_id: TASK_ID })
        .catch((e: unknown) => e);

      expect(error).toBeInstanceOf(HostToolError);
      expect((error as HostToolError).code).toBe(code);
      expect((error as Error).message).toBe("Tool request failed");
    },
  );

  it("fails a success without an object body, and a native rejection, as a retryable failure", async () => {
    const empty = new CompanionRoomTransport(
      fakeNative(() => ({ status: 200, body: null })),
    );
    const down = new CompanionRoomTransport(
      fakeNative(() => {
        throw new Error("no network");
      }),
    );

    await expect(
      empty.call("get_task", { task_id: TASK_ID }),
    ).rejects.toMatchObject({ code: undefined });
    const error = await down
      .call("get_task", { task_id: TASK_ID })
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HostToolError);
    expect((error as HostToolError).code).toBeUndefined();
  });
});
