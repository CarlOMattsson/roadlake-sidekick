import { describe, expect, it, vi } from "vitest";

import { controlEn, controlSv } from "@/features/control-app/labels";
import { createTrashTransport } from "@/features/control-app/trash-transport";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import type { TrashItem } from "@/features/control-app/transport";

/** A mock that answers whatever type the caller asks for, as the transport's generic `call` does. */
const asCall = (mock: unknown) => mock as RoomTransport["call"];

const task: TrashItem = {
  kind: "task",
  id: "019f0000-0000-7000-8000-000000000101",
  label: "Förbered pitchen",
  trashed_at: "2026-10-31T13:30:00Z",
  version: 4,
};

describe("createTrashTransport", () => {
  it("offers reading and restoring, and no deleting, to a host without supportsTool (Claude)", async () => {
    const call = vi.fn(() => Promise.resolve({}));
    const transport = createTrashTransport(asCall(call));

    expect(transport.erase).toBeUndefined();
    expect(transport.empty).toBeUndefined();
    await transport.trash();
    await transport.trash("next");
    await transport.restore(task, "key-1");
    expect(call.mock.calls).toEqual([
      ["list_trash", {}],
      ["list_trash", { cursor: "next" }],
      [
        "restore_from_trash",
        {
          kind: "task",
          record_id: task.id,
          version: 4,
          idempotency_key: "key-1",
        },
      ],
    ]);
  });

  it("offers no deleting when the host says it has no such tool, or answers something other than true", () => {
    const call = vi.fn();
    for (const answer of [false, undefined, 1, "yes"]) {
      const supportsTool = (() => answer) as unknown as (
        name: string,
      ) => boolean;
      const transport = createTrashTransport(asCall(call), supportsTool);
      expect(transport.erase).toBeUndefined();
      expect(transport.empty).toBeUndefined();
    }
  });

  it("calls erase_trashed_task and empty_trash with confirmed true where the host has the tool", async () => {
    const call = vi.fn(() => Promise.resolve({ removed: true }));
    const supportsTool = (name: string) => name === "erase_trashed_task";
    const transport = createTrashTransport(asCall(call), supportsTool);

    await transport.erase?.(task, "key-2");
    await transport.empty?.("key-3");

    expect(call.mock.calls).toEqual([
      [
        "erase_trashed_task",
        {
          task_id: task.id,
          version: 4,
          confirmed: true,
          idempotency_key: "key-2",
        },
      ],
      ["empty_trash", { confirmed: true, idempotency_key: "key-3" }],
    ]);
  });
});

describe("the delete texts", () => {
  it("never speak of confirmation flags", () => {
    for (const labels of [controlSv, controlEn]) {
      const texts = [
        labels.erase,
        labels.eraseQuestion("x"),
        labels.eraseConflict,
        labels.eraseHelp,
        labels.emptyTrash,
        labels.emptyQuestion(2, true),
        labels.emptyDone(1, 1),
      ];
      for (const text of texts) expect(text).not.toMatch(/confirm/i);
    }
  });

  it("cover the same keys in both languages", () => {
    expect(Object.keys(controlEn).sort()).toEqual(
      Object.keys(controlSv).sort(),
    );
  });
});
