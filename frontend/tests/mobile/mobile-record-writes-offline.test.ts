import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { UUID } from "@/mobile/companion-plan";
import {
  CompanionNetworkError,
  CompanionRoomTransport,
} from "@/mobile/companion-transport";
import type { NativeRequest, NativeResponse } from "@/mobile/sidekick-native";
import { fakeNative, nativeError, ok } from "@tests/helpers/fake-native";
import {
  KEY,
  PROJECT_ID,
  TASK_ID,
} from "@tests/helpers/companion-transport-fixtures";

// Tasks, Projects and journal entries written on the phone without a network wait in its outbox and are answered with
// stand-ins, so the room shows what the user wrote. These tests drive the transport against a phone whose writes get no
// answer, while its reads are answered (`reads`, by path).

const ENTRY_ID = "019f0000-0000-7000-8000-0000000000f1";
const DAY = "2026-11-15";
const DAY_PATH = `/companion/v1/journal/days/${DAY}`;

const READ_TASK = {
  id: TASK_ID,
  version: 3,
  title: "Ring revisorn",
  due_at: null,
  status: "todo",
};
const READ_PROJECT = {
  id: PROJECT_ID,
  version: 2,
  title: "Bokslut",
  status: "active",
};
const READ_ENTRY = {
  id: ENTRY_ID,
  version: 4,
  title: "Morgon",
  journal_date: DAY,
  key_points: [],
};

/** Any key: the transport makes one when the room gives none. */
const ANY_KEY = expect.any(String) as string;

/** The phone's writes get no answer; its reads are answered from `reads`, by path. */
function phone(reads: Record<string, unknown> = {}) {
  const native = fakeNative((request: NativeRequest): NativeResponse => {
    if (request.method === "GET" && request.path in reads)
      return ok(reads[request.path]);
    throw nativeError("network", 0);
  });
  return { native, transport: new CompanionRoomTransport(native) };
}

function queuedWrites(native: ReturnType<typeof phone>["native"]) {
  return [...native.records.values()];
}

describe("create_task without an answer", () => {
  it("answers with a stand-in Task and puts the write in the outbox under the key of the first attempt", async () => {
    const { native, transport } = phone();

    const result = await transport.call<{ task: Record<string, unknown> }>(
      "create_task",
      { title: "Ring revisorn", due_at: "2026-12-01" },
    );

    expect(result.task).toMatchObject({
      title: "Ring revisorn",
      due_at: "2026-12-01",
      status: "todo",
      version: 1,
    });
    const id = result.task.id as string;
    expect(id.startsWith("queued-")).toBe(true);
    expect(UUID.test(id)).toBe(false);

    const request = native.requests[0] as NativeRequest;
    expect(native.records.size).toBe(1);
    expect(queuedWrites(native)[0]).toEqual({
      generation: 0,
      kind: "create_task",
      idempotencyKey: request.idempotencyKey,
      body: { title: "Ring revisorn", due_at: "2026-12-01" },
    });
    expect(request.body).toEqual({
      title: "Ring revisorn",
      due_at: "2026-12-01",
    });
    expect(id).toBe(`queued-${request.idempotencyKey}`);
  });

  it("keeps the room's own key, so the outbox sends it with the key the room used", async () => {
    const { native, transport } = phone();

    await transport.call("create_task", {
      title: "Ring revisorn",
      idempotency_key: KEY,
    });

    expect([...native.records.keys()]).toEqual([KEY]);
  });

  it("opens the stand-in with get_task while it waits, and says not_found once it has been sent", async () => {
    const { native, transport } = phone();
    const { task } = await transport.call<{ task: { id: string } }>(
      "create_task",
      { title: "Ring revisorn" },
    );

    await expect(
      transport.call("get_task", { task_id: task.id }),
    ).resolves.toMatchObject({
      task: { id: task.id, title: "Ring revisorn", version: 1 },
    });
    // The stand-in is read from the outbox, not asked of the server.
    expect(native.requests).toHaveLength(1);

    native.runOutbox();

    await expect(
      transport.call("get_task", { task_id: task.id }),
    ).rejects.toMatchObject({
      name: "HostToolError",
      code: "not_found",
    });
  });
});

describe("update_task and update_project without an answer", () => {
  it("lays the change over the Task as it was read, keeps its version and queues the edit", async () => {
    const { native, transport } = phone({
      [`/companion/v1/tasks/${TASK_ID}`]: { task: READ_TASK },
    });
    await transport.call("get_task", { task_id: TASK_ID });

    const result = await transport.call("update_task", {
      task_id: TASK_ID,
      version: 3,
      changes: { title: "Ring revisorn i dag", due_at: "2026-12-01" },
    });

    expect(result).toEqual({
      task: {
        ...READ_TASK,
        title: "Ring revisorn i dag",
        due_at: "2026-12-01",
      },
    });
    expect(queuedWrites(native)).toEqual([
      {
        generation: 0,
        kind: "update_task",
        subjectId: TASK_ID,
        version: 3,
        idempotencyKey: ANY_KEY,
        body: {
          version: 3,
          title: "Ring revisorn i dag",
          due_at: "2026-12-01",
        },
      },
    ]);
  });

  it("queues nothing for a Task it has not read: there is nothing to lay the change over", async () => {
    const { native, transport } = phone();

    await expect(
      transport.call("update_task", {
        task_id: TASK_ID,
        version: 3,
        changes: { title: "Ring revisorn i dag" },
      }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);

    expect(native.records.size).toBe(0);
  });

  it("does not queue a second copy when the room asks again with the same key", async () => {
    const { native, transport } = phone({
      [`/companion/v1/tasks/${TASK_ID}`]: { task: READ_TASK },
    });
    await transport.call("get_task", { task_id: TASK_ID });
    const args = {
      task_id: TASK_ID,
      version: 3,
      changes: { title: "Ring revisorn i dag" },
      idempotency_key: KEY,
    };

    const first = await transport.call("update_task", args);
    const second = await transport.call("update_task", args);

    expect(second).toEqual(first);
    expect(native.records.size).toBe(1);
    expect([...native.records.keys()]).toEqual([KEY]);
  });

  it("lays a second edit over the first, still resting on the version the server has", async () => {
    const { native, transport } = phone({
      [`/companion/v1/tasks/${TASK_ID}`]: { task: READ_TASK },
    });
    await transport.call("get_task", { task_id: TASK_ID });

    await transport.call("update_task", {
      task_id: TASK_ID,
      version: 3,
      changes: { title: "Ring revisorn i dag" },
    });
    const second = await transport.call("update_task", {
      task_id: TASK_ID,
      version: 3,
      changes: { due_at: "2026-12-01" },
    });

    expect(second).toEqual({
      task: {
        ...READ_TASK,
        title: "Ring revisorn i dag",
        due_at: "2026-12-01",
      },
    });
    expect(native.records.size).toBe(2);
  });

  it("does the same for update_project", async () => {
    const { native, transport } = phone({
      [`/companion/v1/projects/${PROJECT_ID}`]: { project: READ_PROJECT },
    });
    await transport.call("get_project", { project_id: PROJECT_ID });

    const result = await transport.call("update_project", {
      project_id: PROJECT_ID,
      version: 2,
      changes: { title: "Bokslut 2026", target_date: "2026-12-31" },
    });

    expect(result).toEqual({
      project: {
        ...READ_PROJECT,
        title: "Bokslut 2026",
        target_date: "2026-12-31",
      },
    });
    expect(queuedWrites(native)).toEqual([
      {
        generation: 0,
        kind: "update_project",
        subjectId: PROJECT_ID,
        version: 2,
        idempotencyKey: ANY_KEY,
        body: { version: 2, title: "Bokslut 2026", target_date: "2026-12-31" },
      },
    ]);
  });

  it("queues no edit of a Project it has not read", async () => {
    const { native, transport } = phone();

    await expect(
      transport.call("update_project", {
        project_id: PROJECT_ID,
        version: 2,
        changes: { title: "Bokslut 2026" },
      }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);

    expect(native.records.size).toBe(0);
  });
});

describe("journal writes without an answer", () => {
  it("answers write_journal_entry with a stand-in entry for the day", async () => {
    const { native, transport } = phone();

    const result = await transport.call<{ entry: Record<string, unknown> }>(
      "write_journal_entry",
      { journal_date: DAY, title: "Kväll", source_text: "En lugn dag." },
    );

    expect(result.entry).toMatchObject({
      journal_date: DAY,
      title: "Kväll",
      version: 1,
    });
    expect((result.entry.id as string).startsWith("queued-")).toBe(true);
    expect(queuedWrites(native)).toMatchObject([
      {
        kind: "write_journal_entry",
        body: {
          journal_date: DAY,
          title: "Kväll",
          source_text: "En lugn dag.",
        },
      },
    ]);
  });

  it("adds the waiting entry to the day the server answers, and not once it has been sent", async () => {
    const { native, transport } = phone({
      [DAY_PATH]: { journal_date: DAY, entries: [READ_ENTRY] },
    });
    const { entry } = await transport.call<{ entry: { id: string } }>(
      "write_journal_entry",
      { journal_date: DAY, title: "Kväll", source_text: "En lugn dag." },
    );

    const waiting = await transport.call<{ entries: { id: string }[] }>(
      "get_journal_day",
      { journal_date: DAY },
    );
    expect(waiting.entries.map((row) => row.id)).toEqual([ENTRY_ID, entry.id]);

    native.runOutbox();

    const sent = await transport.call<{ entries: { id: string }[] }>(
      "get_journal_day",
      { journal_date: DAY },
    );
    expect(sent.entries.map((row) => row.id)).toEqual([ENTRY_ID]);
  });

  it("leaves another day alone", async () => {
    const other = "2026-11-14";
    const { transport } = phone({
      [`/companion/v1/journal/days/${other}`]: {
        journal_date: other,
        entries: [],
      },
    });
    await transport.call("write_journal_entry", {
      journal_date: DAY,
      title: "Kväll",
      source_text: "En lugn dag.",
    });

    await expect(
      transport.call("get_journal_day", { journal_date: other }),
    ).resolves.toEqual({ journal_date: other, entries: [] });
  });

  it("lays the change of update_journal_entry over the entry as it was read, with the same version", async () => {
    const { native, transport } = phone({
      [`/companion/v1/journal/entries/${ENTRY_ID}`]: { entry: READ_ENTRY },
    });
    await transport.call("get_journal_entry", { entry_id: ENTRY_ID });

    const result = await transport.call("update_journal_entry", {
      entry_id: ENTRY_ID,
      expected_version: 4,
      title: "Morgon och kväll",
    });

    expect(result).toEqual({
      entry: { ...READ_ENTRY, title: "Morgon och kväll" },
    });
    expect(queuedWrites(native)).toEqual([
      {
        generation: 0,
        kind: "update_journal_entry",
        subjectId: ENTRY_ID,
        version: 4,
        idempotencyKey: ANY_KEY,
        body: { version: 4, title: "Morgon och kväll" },
      },
    ]);
  });

  it("queues no edit of an entry it has not read", async () => {
    const { native, transport } = phone();

    await expect(
      transport.call("update_journal_entry", {
        entry_id: ENTRY_ID,
        expected_version: 4,
        title: "Morgon och kväll",
      }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);

    expect(native.records.size).toBe(0);
  });
});

describe("what is not queued", () => {
  it("fails with the connection error when the phone refuses to keep the write", async () => {
    const { native, transport } = phone();
    native.queueRecordWrite.mockResolvedValue({ queued: false });

    await expect(
      transport.call("create_task", { title: "Ring revisorn" }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);
    expect(native.records.size).toBe(0);
  });

  it("fails with the connection error when the phone cannot be asked to keep it", async () => {
    const { native, transport } = phone();
    native.queueRecordWrite.mockRejectedValue(new Error("unavailable"));

    await expect(
      transport.call("create_task", { title: "Ring revisorn" }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);
  });

  it("does not queue a request that failed without the pairing it began under", async () => {
    const native = fakeNative(() => {
      throw nativeError("network");
    });
    const transport = new CompanionRoomTransport(native);

    await expect(
      transport.call("create_task", { title: "Ring revisorn" }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);
    expect(native.queueRecordWrite).not.toHaveBeenCalled();
  });

  it("queues a write that timed out as it queues one without a network", async () => {
    const native = fakeNative(() => {
      throw nativeError("timeout", 0);
    });
    const transport = new CompanionRoomTransport(native);

    await transport.call("create_task", { title: "Ring revisorn" });

    expect(native.records.size).toBe(1);
  });

  it("never queues an answer that is a refusal: a 409 is a conflict", async () => {
    const native = fakeNative(() => ({ status: 409, body: {} }));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("create_task", { title: "Ring revisorn" })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(HostToolError);
    expect((error as HostToolError).code).toBe("conflict");
    expect(native.records.size).toBe(0);
    expect(native.queueRecordWrite).not.toHaveBeenCalled();
  });

  it("never queues an answer of a server error either", async () => {
    const native = fakeNative(() => ({ status: 503, body: {} }));
    const transport = new CompanionRoomTransport(native);

    const error = await transport
      .call("create_task", { title: "Ring revisorn" })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(HostToolError);
    expect(native.records.size).toBe(0);
    expect(native.queueRecordWrite).not.toHaveBeenCalled();
  });
});

describe("what waits, as the rooms read it", () => {
  it("names the stand-in of a new Task and the Task of an edit, in lower case, until the outbox has sent them", async () => {
    const { native, transport } = phone({
      [`/companion/v1/tasks/${TASK_ID}`]: { task: READ_TASK },
    });
    await expect(transport.offline.queuedRecordIds?.()).resolves.toEqual(
      new Set(),
    );
    await transport.call("get_task", { task_id: TASK_ID });
    const { task } = await transport.call<{ task: { id: string } }>(
      "create_task",
      { title: "Ring revisorn" },
    );
    await transport.call("update_task", {
      task_id: TASK_ID.toUpperCase(),
      version: 3,
      changes: { title: "Ring revisorn i dag" },
    });

    await expect(transport.offline.queuedRecordIds?.()).resolves.toEqual(
      new Set([task.id, TASK_ID]),
    );

    native.runOutbox();

    await expect(transport.offline.queuedRecordIds?.()).resolves.toEqual(
      new Set(),
    );
  });

  it("tells the room's listener when the transport puts a write in the outbox, and when the outbox has run", async () => {
    const { native, transport } = phone();
    const listener = vi.fn();
    const stop = transport.offline.onQueueChanged(listener);

    await transport.call("create_task", { title: "Ring revisorn" });
    expect(listener).toHaveBeenCalledTimes(1);

    native.runOutbox();
    await vi.waitFor(() => expect(listener).toHaveBeenCalledTimes(2));

    stop();
    await transport.call("create_task", { title: "Ring revisorn igen" });
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("what the transport answers for these tools", () => {
  it("lists the five writes", () => {
    const { transport } = phone();
    for (const tool of [
      "create_task",
      "update_task",
      "update_project",
      "write_journal_entry",
      "update_journal_entry",
    ])
      expect(transport.supportsTool?.(tool), tool).toBe(true);
  });

  it("answers the calls of the edit fields, and still not the ones the routes do not take", () => {
    const { transport } = phone();
    const supports = (name: string, args: object) =>
      transport.supportsCall?.(name, args);

    expect(supports("create_task", { title: "A" })).toBe(true);
    expect(
      supports("update_task", { task_id: TASK_ID, changes: { title: "A" } }),
    ).toBe(true);
    expect(
      supports("update_task", { task_id: TASK_ID, changes: { tags: ["a"] } }),
    ).toBe(false);
    expect(
      supports("update_project", {
        project_id: PROJECT_ID,
        changes: { title: "A" },
      }),
    ).toBe(true);
    expect(
      supports("update_project", {
        project_id: PROJECT_ID,
        changes: { tags: ["a"] },
      }),
    ).toBe(false);
    expect(supports("write_journal_entry", { title: "A" })).toBe(true);
    expect(
      supports("update_journal_entry", { entry_id: ENTRY_ID, title: "A" }),
    ).toBe(true);
    expect(
      supports("update_journal_entry", { entry_id: ENTRY_ID, tags: ["a"] }),
    ).toBe(false);
    expect(
      supports("update_journal_entry", {
        entry_id: ENTRY_ID,
        add_project_ids: [PROJECT_ID],
      }),
    ).toBe(false);
  });
});
