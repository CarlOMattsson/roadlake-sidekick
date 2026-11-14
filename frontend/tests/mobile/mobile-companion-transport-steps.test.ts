import { describe, expect, it } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  COMPANION_ROUTES,
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { JOURNAL_ROUTES } from "@/mobile/companion-journal";
import { LICENSE_ROUTES } from "@/mobile/companion-license";
import { SHOPPING_ROUTES } from "@/mobile/companion-shopping";
import { fakeNative, ok } from "@tests/helpers/fake-native";
import {
  KEY,
  PROJECT_ID,
  DOMAIN_ID,
  PROCESS_ID,
  STEP_ID,
} from "@tests/helpers/companion-transport-fixtures";
import { readRepoFile } from "@tests/helpers/source-files";

describe("CompanionRoomTransport Step ticks", () => {
  const complete = { step_id: STEP_ID, version: 3 };
  const reopen = { ...complete, changes: { status: "todo" } };

  it("maps complete_task_step to POST /steps/{id}/complete with version in the body and the room's key", async () => {
    const native = fakeNative(() => ok({ step: { id: STEP_ID, version: 4 } }));
    const transport = new CompanionRoomTransport(native);

    const result = await transport.call("complete_task_step", {
      ...complete,
      idempotency_key: KEY,
    });

    expect(result).toEqual({ step: { id: STEP_ID, version: 4 } });
    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/steps/${STEP_ID}/complete`,
        body: { version: 3 },
        idempotencyKey: KEY,
      },
    ]);
  });

  it("maps update_task_step to todo onto POST /steps/{id}/reopen with version in the body and the room's key", async () => {
    const native = fakeNative(() => ok({ step: { id: STEP_ID, version: 4 } }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("update_task_step", {
      ...reopen,
      idempotency_key: KEY,
    });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/steps/${STEP_ID}/reopen`,
        body: { version: 3 },
        idempotencyKey: KEY,
      },
    ]);
  });

  it.each([
    ["another status", { status: "in_progress" }],
    ["completed (that is complete_task_step)", { status: "completed" }],
    ["todo with a title", { status: "todo", title: "x" }],
    ["a title only", { title: "x" }],
    ["a due date", { due_at: null }],
    ["no changes", {}],
    ["changes that are not an object", "todo"],
  ])(
    "refuses update_task_step with %s as 'not in the app' and sends nothing",
    async (_label, changes) => {
      const native = fakeNative(() => ok({}));
      const transport = new CompanionRoomTransport(native);

      const error = await transport
        .call("update_task_step", { ...complete, changes })
        .catch((e: unknown) => e);

      expect(error).toBeInstanceOf(NotInAppError);
      expect(native.requests).toEqual([]);
    },
  );

  it("refuses update_task_step without changes as 'not in the app'", async () => {
    const native = fakeNative(() => ok({}));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("update_task_step", complete)
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(NotInAppError);
    expect(native.requests).toEqual([]);
  });

  it.each([
    ["complete_task_step", complete, "complete"],
    ["update_task_step", reopen, "reopen"],
  ])(
    "%s without a key of the room's own: the same key on a retry after a 5xx or no answer, a new one once a 4xx settled it",
    async (name, args, route) => {
      const steps: Array<number | "down"> = [503, "down", 200, 409, 200];
      const native = fakeNative(() => {
        const next = steps.shift();
        if (next === "down") throw new Error("timeout");
        return { status: next ?? 200, body: { step: {} } };
      });
      const transport = new CompanionRoomTransport(native);

      await transport.call(name, args).catch(() => undefined); // 503
      await transport.call(name, args).catch(() => undefined); // no answer
      await transport.call(name, args); // 200: settled
      await transport.call(name, args).catch(() => undefined); // 409: settled too
      await transport.call(name, args); // a new action

      const keys = native.requests.map((request) => request.idempotencyKey);
      expect(native.requests.every((r) => r.path.endsWith(`/${route}`))).toBe(
        true,
      );
      expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
      expect(keys[1]).toBe(keys[0]);
      expect(keys[2]).toBe(keys[0]);
      expect(keys[3]).not.toBe(keys[0]);
      expect(keys[4]).not.toBe(keys[3]);
    },
  );

  it("keeps the keys of a Task and of a Step with the same id and version apart, and complete apart from reopen", async () => {
    const native = fakeNative(() => ({ status: 503, body: null }));
    const transport = new CompanionRoomTransport(native);

    await transport.call("complete_task_step", complete).catch(() => undefined);
    await transport.call("update_task_step", reopen).catch(() => undefined);
    await transport
      .call("complete_task", { task_id: STEP_ID, version: 3 })
      .catch(() => undefined);

    const keys = native.requests.map((request) => request.idempotencyKey);
    expect(new Set(keys).size).toBe(3);
  });

  it("sends the room's own key as it is on every retry of a Step write", async () => {
    const native = fakeNative(() => ({ status: 503, body: null }));
    const transport = new CompanionRoomTransport(native);
    const args = { ...complete, idempotency_key: KEY };

    await transport.call("complete_task_step", args).catch(() => undefined);
    await transport.call("complete_task_step", args).catch(() => undefined);

    expect(native.requests.map((r) => r.idempotencyKey)).toEqual([KEY, KEY]);
  });
});

describe("CompanionRoomTransport tool lists", () => {
  it("answers every new tool name", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    for (const name of [
      "get_work_hierarchy",
      "get_project",
      "list_tasks",
      "get_domain",
      "get_process",
      "complete_task_step",
      "update_task_step",
    ])
      expect(transport.supportsTool(name)).toBe(true);
    // Writes to a Project or a Task that have no route stay out.
    for (const name of [
      "update_project",
      "create_task",
      "archive_task_step",
      "reorder_task_steps",
      "add_task_step",
    ])
      expect(transport.supportsTool(name)).toBe(false);
  });

  it("answers the plain reads and the Step tick in full", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    for (const name of [
      "get_work_hierarchy",
      "get_project",
      "get_domain",
      "get_process",
      "complete_task_step",
    ])
      expect(transport.supportsCall(name, {})).toBe(true);
  });

  it("answers list_tasks only for a Project's page or a Process's first page", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    expect(
      transport.supportsCall("list_tasks", { project_id: PROJECT_ID }),
    ).toBe(true);
    expect(
      transport.supportsCall("list_tasks", {
        project_id: PROJECT_ID,
        limit: 20,
        cursor: null,
      }),
    ).toBe(true);
    expect(
      transport.supportsCall("list_tasks", {
        process_id: PROCESS_ID,
        limit: 20,
      }),
    ).toBe(true);
    for (const args of [
      {},
      { unsorted: true },
      { process_id: PROCESS_ID, cursor: "abc" },
      { process_id: "not-a-uuid" },
      { process_id: PROCESS_ID, status: "todo" },
      { project_id: PROJECT_ID, process_id: PROCESS_ID },
      { project_id: PROJECT_ID, status: "todo" },
      { project_id: "not-a-uuid" },
      undefined,
    ])
      expect(transport.supportsCall("list_tasks", args as object)).toBe(false);
  });

  it("answers get_work_hierarchy with its Tasks, also of one Process, and nothing it does not take", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    for (const args of [
      { include_tasks: true },
      { include_tasks: true, process_id: PROCESS_ID, limit: 1 },
      { limit: 100, cursor: "abc" },
    ])
      expect(transport.supportsCall("get_work_hierarchy", args)).toBe(true);
    for (const args of [
      { process_id: PROCESS_ID },
      { include_tasks: true, process_id: "x" },
      { include_tasks: "true" },
      { status: "todo" },
      { limit: "5" },
    ])
      expect(transport.supportsCall("get_work_hierarchy", args)).toBe(false);
  });

  it("answers update_task_step only for the change back to todo", () => {
    const transport = new CompanionRoomTransport(fakeNative(() => ok({})));

    expect(
      transport.supportsCall("update_task_step", {
        changes: { status: "todo" },
      }),
    ).toBe(true);
    for (const changes of [
      { status: "completed" },
      { status: "in_progress" },
      { status: "todo", title: "x" },
      { title: "x" },
      {},
      undefined,
    ])
      expect(transport.supportsCall("update_task_step", { changes })).toBe(
        false,
      );
    expect(transport.supportsCall("update_task_step", {})).toBe(false);
  });
});

describe("CompanionRoomTransport errors on the new routes", () => {
  it.each([
    ["get_project", { project_id: PROJECT_ID }],
    ["get_domain", { domain_id: DOMAIN_ID }],
    ["get_process", { process_id: PROCESS_ID }],
    ["get_work_hierarchy", {}],
    ["list_tasks", { project_id: PROJECT_ID }],
    [
      "complete_task_step",
      { step_id: STEP_ID, version: 1, idempotency_key: KEY },
    ],
    [
      "update_task_step",
      {
        step_id: STEP_ID,
        version: 1,
        idempotency_key: KEY,
        changes: { status: "todo" },
      },
    ],
  ])(
    "turns 404 and 409 of %s into not_found and conflict",
    async (name, args) => {
      for (const [status, code] of [
        [404, "not_found"],
        [409, "conflict"],
      ] as const) {
        const transport = new CompanionRoomTransport(
          fakeNative(() => ({ status, body: null })),
        );

        const error = await transport.call(name, args).catch((e: unknown) => e);

        expect(error).toBeInstanceOf(HostToolError);
        expect((error as HostToolError).code).toBe(code);
      }
    },
  );

  it("passes on the server's own error code from a problem+json body, and drops one that is free text", async () => {
    const own = new CompanionRoomTransport(
      fakeNative(() => ({
        status: 409,
        body: { type: "about:blank", code: "version_mismatch", status: 409 },
      })),
    );
    const free = new CompanionRoomTransport(
      fakeNative(() => ({ status: 409, body: { code: "Version is stale!" } })),
    );
    const args = { step_id: STEP_ID, version: 1, idempotency_key: KEY };

    const passed = await own
      .call("complete_task_step", args)
      .catch((e: unknown) => e);
    const dropped = await free
      .call("complete_task_step", args)
      .catch((e: unknown) => e);

    expect((passed as HostToolError).code).toBe("version_mismatch");
    // Not a closed code: the status decides.
    expect((dropped as HostToolError).code).toBe("conflict");
  });
});

describe("companion route tables against the published contract", () => {
  /**
   * The (method, path) pairs of contracts/companion-api.generated.json, which the backend generates
   * from its registered routes (CI fails when it is stale). Path parameters keep their names.
   */
  function contractRoutes(): Set<string> {
    const contract = JSON.parse(
      readRepoFile("contracts/companion-api.generated.json"),
    ) as { paths: Record<string, Record<string, unknown>> };
    return new Set(
      Object.entries(contract.paths).flatMap(([route, item]) =>
        Object.keys(item).map((method) => `${method.toUpperCase()} ${route}`),
      ),
    );
  }

  const tables = {
    ...COMPANION_ROUTES,
    ...SHOPPING_ROUTES,
    ...JOURNAL_ROUTES,
    ...LICENSE_ROUTES,
  };
  const ours = Object.values(tables).map(
    (route) => `${route.method} ${route.path}`,
  );

  it("reads the contract (the file has routes and the transport knows some of them)", () => {
    expect(contractRoutes().size).toBeGreaterThanOrEqual(ours.length);
    expect(ours).toContain("POST /companion/v1/steps/{step_id}/reopen");
  });

  it.each(ours)("the backend serves %s", (route) => {
    expect(contractRoutes()).toContain(route);
  });

  it("has a route for every backend path the rooms read or write (work, shopping, journal, license)", () => {
    const wanted =
      /^[A-Z]+ \/companion\/v1\/(work\/(agenda|hierarchy)|tasks|projects|domains|processes|steps|shopping|journal|license)(\/|$)/;
    const missing = [...contractRoutes()].filter(
      (route) => wanted.test(route) && !ours.includes(route),
    );
    expect(missing).toEqual([]);
  });
});
