import { expect, it } from "vitest";
import { clearWire } from "@/lib/mcp/clear-wire";

it("moves nulls in changes to clear, in order", () => {
  expect(
    clearWire("update_task", {
      task_id: "t",
      changes: { project_id: null, title: "x", due_at: null },
    }),
  ).toEqual({
    task_id: "t",
    changes: { title: "x" },
    clear: ["project_id", "due_at"],
  });
});

it("sends no clear when nothing is null", () => {
  const args = { task_id: "t", changes: { title: "x" } };
  expect(clearWire("update_task", args)).toBe(args);
});

it("reads the item of a shopping item, not changes", () => {
  expect(
    clearWire("update_shopping_item", {
      item_id: "i",
      item: { note: null, name: "Mjölk" },
    }),
  ).toEqual({ item_id: "i", item: { name: "Mjölk" }, clear: ["note"] });
});

it("never touches tags", () => {
  expect(
    clearWire("update_task", { changes: { tags: [], due_at: null } }),
  ).toEqual({ changes: { tags: [] }, clear: ["due_at"] });
});

it("keeps a null on a field the server cannot empty", () => {
  expect(
    clearWire("update_task", { changes: { title: null, note: null } }),
  ).toEqual({ changes: { title: null, note: null } });
});

it("merges with a clear that is already there, without repeats", () => {
  expect(
    clearWire("update_project", {
      changes: { description: null, target_date: null },
      clear: ["description", "start_date"],
    }),
  ).toEqual({
    changes: {},
    clear: ["description", "start_date", "target_date"],
  });
});

it("passes other tools through unchanged", () => {
  const args = { changes: { due_at: null } };
  expect(clearWire("create_task", args)).toBe(args);
  expect(clearWire("toString", args)).toBe(args);
});
