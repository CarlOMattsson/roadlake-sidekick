import { describe, expect, it } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  CompanionRoomTransport,
  NotInAppError,
} from "@/mobile/companion-transport";
import { fakeNative, ok } from "@tests/helpers/fake-native";
import { KEY, TASK_ID } from "@tests/helpers/companion-transport-fixtures";

const RECORD = {
  kind: "task",
  id: TASK_ID,
  label: "Ring revisorn",
  trashed_at: "2026-11-15T10:00:00+01:00",
  version: 3,
};

describe("move_to_trash and restore_from_trash over the companion routes", () => {
  it.each([
    ["task", "tasks"],
    ["journal_entry", "journal/entries"],
    ["shopping_item", "shopping/items"],
  ])(
    "sends a %s to its own trash and untrash route with the version and key",
    async (kind, collection) => {
      const native = fakeNative(() => ok(RECORD));
      const transport = new CompanionRoomTransport(native);

      await transport.call("move_to_trash", {
        kind,
        record_id: TASK_ID.toUpperCase(),
        version: 2,
        idempotency_key: KEY,
      });
      await transport.call("restore_from_trash", {
        kind,
        record_id: TASK_ID,
        version: 3,
        idempotency_key: KEY,
      });

      expect(native.requests).toEqual([
        {
          method: "POST",
          path: `/companion/v1/${collection}/${TASK_ID}/trash`,
          body: { version: 2 },
          idempotencyKey: KEY,
        },
        {
          method: "POST",
          path: `/companion/v1/${collection}/${TASK_ID}/untrash`,
          body: { version: 3 },
          idempotencyKey: KEY,
        },
      ]);
    },
  );

  it("answers no for every kind the app has no route for, before anything is sent", async () => {
    const native = fakeNative(() => ok(RECORD));
    const transport = new CompanionRoomTransport(native);

    for (const kind of ["project", "contact", "step", "domain"]) {
      expect(transport.supportsCall("move_to_trash", { kind })).toBe(false);
      expect(transport.supportsCall("restore_from_trash", { kind })).toBe(
        false,
      );
      await expect(
        transport.call("move_to_trash", {
          kind,
          record_id: TASK_ID,
          version: 1,
        }),
      ).rejects.toBeInstanceOf(NotInAppError);
    }
    expect(transport.supportsCall("move_to_trash", { kind: "task" })).toBe(
      true,
    );
    expect(native.requests).toEqual([]);
  });

  it("refuses a bad id, a bad version and an extra argument", async () => {
    const native = fakeNative(() => ok(RECORD));
    const transport = new CompanionRoomTransport(native);
    const base = { kind: "task", record_id: TASK_ID, version: 1 };

    for (const bad of [
      { ...base, record_id: "not-an-id" },
      { ...base, version: 0 },
      { ...base, extra: true },
    ]) {
      await expect(transport.call("move_to_trash", bad)).rejects.toMatchObject({
        code: "validation_error",
      });
    }
    expect(native.requests).toEqual([]);
  });
});

describe("list_trash over the companion route", () => {
  it("reads GET /companion/v1/trash with only its own query", async () => {
    const native = fakeNative(() =>
      ok({ items: [RECORD], has_more: false, next_cursor: null }),
    );
    const transport = new CompanionRoomTransport(native);

    await transport.call("list_trash", { kind: "task", cursor: null });
    await transport.call("list_trash", {});

    expect(native.requests).toEqual([
      { method: "GET", path: "/companion/v1/trash", query: { kind: "task" } },
      { method: "GET", path: "/companion/v1/trash" },
    ]);
    expect(transport.supportsCall("list_trash", { kind: "project" })).toBe(
      false,
    );
    await expect(
      transport.call("list_trash", { kind: "project" }),
    ).rejects.toBeInstanceOf(NotInAppError);
    await expect(
      transport.call("list_trash", { owner_id: TASK_ID }),
    ).rejects.toBeInstanceOf(HostToolError);
  });
});

describe("permanent removal over the companion routes", () => {
  it("is refused before anything is sent unless the caller passes confirmed: true", async () => {
    const native = fakeNative(() => ok({ removed: true }));
    const transport = new CompanionRoomTransport(native);

    for (const confirmed of [undefined, false, "yes", 1]) {
      await expect(
        transport.call("erase_trashed_task", {
          task_id: TASK_ID,
          version: 3,
          ...(confirmed === undefined ? {} : { confirmed }),
        }),
      ).rejects.toMatchObject({ code: "validation_error" });
      await expect(
        transport.call("empty_trash", {
          ...(confirmed === undefined ? {} : { confirmed }),
        }),
      ).rejects.toMatchObject({ code: "validation_error" });
    }
    expect(native.requests).toEqual([]);
  });

  it("sends the explicit confirmation to the erase and empty routes", async () => {
    const native = fakeNative((request) =>
      ok(
        request.path.endsWith("/empty")
          ? { removed: 2, kept: 1 }
          : { removed: true },
      ),
    );
    const transport = new CompanionRoomTransport(native);

    await expect(
      transport.call("erase_trashed_task", {
        task_id: TASK_ID,
        version: 3,
        confirmed: true,
        idempotency_key: KEY,
      }),
    ).resolves.toEqual({ removed: true });
    await expect(
      transport.call("empty_trash", { confirmed: true, idempotency_key: KEY }),
    ).resolves.toEqual({ removed: 2, kept: 1 });

    expect(native.requests).toEqual([
      {
        method: "POST",
        path: `/companion/v1/tasks/${TASK_ID}/erase`,
        body: { version: 3, confirm: true },
        idempotencyKey: KEY,
      },
      {
        method: "POST",
        path: "/companion/v1/trash/empty",
        body: { confirm: true },
        idempotencyKey: KEY,
      },
    ]);
  });
});
