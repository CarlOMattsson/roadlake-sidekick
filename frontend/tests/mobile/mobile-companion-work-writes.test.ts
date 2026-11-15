import { describe, expect, it } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  CompanionNetworkError,
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { fakeNative, ok } from "@tests/helpers/fake-native";
import {
  DOMAIN_ID,
  KEY,
  PROCESS_ID,
  PROJECT_ID,
  TASK_ID,
} from "@tests/helpers/companion-transport-fixtures";

const TASK = { task: { id: TASK_ID, version: 2, title: "Ring revisorn" } };

describe("create_task over the companion route", () => {
  it("posts the typed title, the place and the due date to POST /companion/v1/tasks with the key", async () => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);

    const result = await transport.call("create_task", {
      title: "Ring revisorn",
      project_id: PROJECT_ID.toUpperCase(),
      due_at: "2026-12-01",
      idempotency_key: KEY,
    });

    expect(result).toEqual(TASK);
    expect(native.requests).toEqual([
      {
        method: "POST",
        path: "/companion/v1/tasks",
        body: {
          title: "Ring revisorn",
          project_id: PROJECT_ID,
          due_at: "2026-12-01",
        },
        idempotencyKey: KEY,
      },
    ]);
  });

  it("drops a null (a new Task has none to clear) and takes a process or a domain as the place", async () => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);

    await transport.call("create_task", {
      title: "A",
      process_id: PROCESS_ID,
      due_at: null,
      idempotency_key: KEY,
    });
    await transport.call("create_task", {
      title: "B",
      domain_id: DOMAIN_ID,
      idempotency_key: KEY,
    });

    expect(native.requests.map((request) => request.body)).toEqual([
      { title: "A", process_id: PROCESS_ID },
      { title: "B", domain_id: DOMAIN_ID },
    ]);
  });

  it("keeps the key of an unanswered create for the retry, so one title is never two Tasks", async () => {
    let calls = 0;
    const native = fakeNative(() => {
      calls += 1;
      if (calls === 1) throw Object.assign(new Error("x"), { code: "network" });
      return ok(TASK);
    });
    const transport = new CompanionRoomTransport(native);
    const args = { title: "Ring revisorn" };

    const first = await transport
      .call("create_task", args)
      .catch((e: unknown) => e);
    await transport.call("create_task", args);

    expect(first).toBeInstanceOf(CompanionNetworkError);
    const keys = native.requests.map((request) => request.idempotencyKey);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it.each([
    ["no title", {}],
    ["a title that is not text", { title: 5 }],
    ["a place that is not a uuid", { title: "x", project_id: "../x" }],
    ["a field the route does not take", { title: "x", tags: ["a"] }],
    ["a field the route does not take (owner)", { title: "x", owner_id: "1" }],
  ])("refuses %s before anything is sent", async (_label, args) => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("create_task", args)
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(HostToolError);
    expect((error as HostToolError).code).toBe("validation_error");
    expect(native.requests).toEqual([]);
  });
});

describe("update_task edits over the companion route", () => {
  it("posts the changed fields and the version to POST .../update, null clearing a date or the place", async () => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);

    await transport.call("update_task", {
      task_id: TASK_ID,
      version: 3,
      idempotency_key: KEY,
      changes: {
        title: "Nytt namn",
        due_at: null,
        project_id: PROJECT_ID,
        process_id: null,
        domain_id: null,
        priority: "high",
        description: "Anteckning",
      },
    });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/tasks/${TASK_ID}/update`,
        body: {
          version: 3,
          title: "Nytt namn",
          description: "Anteckning",
          due_at: null,
          project_id: PROJECT_ID,
          process_id: null,
          domain_id: null,
          priority: "high",
        },
        idempotencyKey: KEY,
      },
    ]);
  });

  it("still sends the tick and its undo to their own routes", async () => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);
    const base = { task_id: TASK_ID, version: 1, idempotency_key: KEY };

    await transport.call("update_task", {
      ...base,
      changes: { status: "completed" },
    });
    await transport.call("update_task", {
      ...base,
      changes: { status: "todo" },
    });

    expect(native.requests.map((request) => request.path)).toEqual([
      `/companion/v1/tasks/${TASK_ID}/complete`,
      `/companion/v1/tasks/${TASK_ID}/reopen`,
    ]);
  });

  it.each([
    ["a title that is null", { title: null }],
    ["a priority that is null", { priority: null }],
    ["a place that is not a uuid", { project_id: "x" }],
  ])("refuses %s before anything is sent", async (_label, changes) => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("update_task", {
        task_id: TASK_ID,
        version: 1,
        idempotency_key: KEY,
        changes,
      })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(HostToolError);
    expect(native.requests).toEqual([]);
  });

  it.each([
    ["tags", { tags: ["a"] }],
    ["a repeat rule", { recurrence: null }],
    ["an estimate", { estimated_minutes: 20 }],
    ["a status other than done and open", { status: "in_progress" }],
    ["a status next to an edit", { status: "completed", title: "x" }],
    ["nothing", {}],
  ])("does not answer an update with %s", async (_label, changes) => {
    const native = fakeNative(() => ok(TASK));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("update_task", {
        task_id: TASK_ID,
        version: 1,
        idempotency_key: KEY,
        changes,
      })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(NotInAppError);
    expect(native.requests).toEqual([]);
    expect(transport.supportsCall("update_task", { changes })).toBe(false);
  });
});

describe("update_project over the companion route", () => {
  it("posts title, status, description and dates and the version to POST .../update", async () => {
    const native = fakeNative(() => ok({ project: { id: PROJECT_ID } }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("update_project", {
      project_id: PROJECT_ID,
      version: 4,
      idempotency_key: KEY,
      changes: {
        title: "Flytten",
        status: "paused",
        description: null,
        start_date: "2026-12-01",
        target_date: null,
      },
    });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/projects/${PROJECT_ID}/update`,
        body: {
          version: 4,
          title: "Flytten",
          status: "paused",
          description: null,
          start_date: "2026-12-01",
          target_date: null,
        },
        idempotencyKey: KEY,
      },
    ]);
  });

  it.each([
    ["tags", { tags: ["a"] }],
    ["another domain", { domain_id: DOMAIN_ID }],
    ["a definition of done", { definition_of_done: "x" }],
    ["nothing", {}],
  ])("refuses %s before anything is sent", async (_label, changes) => {
    const native = fakeNative(() => ok({}));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("update_project", {
        project_id: PROJECT_ID,
        version: 1,
        idempotency_key: KEY,
        changes,
      })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(HostToolError);
    expect(native.requests).toEqual([]);
    expect(transport.supportsCall("update_project", { changes })).toBe(false);
  });

  it("refuses a title or a status that is null (they cannot be cleared) before anything is sent", async () => {
    const native = fakeNative(() => ok({}));
    const transport = new CompanionRoomTransport(native);

    for (const changes of [{ title: null }, { status: null }]) {
      const error = await transport
        .call("update_project", {
          project_id: PROJECT_ID,
          version: 1,
          idempotency_key: KEY,
          changes,
        })
        .catch((e: unknown) => e);
      expect(error).toBeInstanceOf(HostToolError);
    }
    expect(native.requests).toEqual([]);
  });

  it("is offered for its edit fields and as a tool", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    expect(transport.supportsTool("update_project")).toBe(true);
    expect(transport.supportsCall("update_project", {})).toBe(true);
    expect(
      transport.supportsCall("update_project", { changes: { title: "x" } }),
    ).toBe(true);
  });
});
