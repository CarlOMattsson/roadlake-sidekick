import { describe, expect, it } from "vitest";
import {
  orderGroupTasks,
  sharedTaskTags,
} from "@/features/work-app/hierarchy/group-task-order";
import type { WorkTaskSummary } from "@/features/work-app/transport/transport";

function task(
  id: string,
  due_at: string | null,
  status = "todo",
  tags?: string[],
): WorkTaskSummary {
  return { id, title: id, status, due_at, tags };
}

const ids = (tasks: WorkTaskSummary[]) => tasks.map((item) => item.id);

describe("orderGroupTasks", () => {
  it("puts the overdue Tasks first with the oldest on top, then by due date, then the ones without a date", () => {
    const { open } = orderGroupTasks([
      task("nodate-1", null),
      task("later", "2026-12-24T22:59:00Z"),
      task("old", "2026-11-02T22:59:00Z"),
      task("nodate-2", null),
      task("soon", "2026-11-26T22:59:00Z"),
      task("late", "2026-11-18T22:59:00Z"),
    ]);
    expect(ids(open)).toEqual([
      "old",
      "late",
      "soon",
      "later",
      "nodate-1",
      "nodate-2",
    ]);
  });

  it("keeps the server's order among Tasks with the same due time", () => {
    const { open } = orderGroupTasks([
      task("b", "2026-11-26T22:59:00Z"),
      task("a", "2026-11-26T22:59:00Z"),
    ]);
    expect(ids(open)).toEqual(["b", "a"]);
  });

  it("treats an unreadable due time as no date", () => {
    const { open } = orderGroupTasks([
      task("broken", "not a date"),
      task("dated", "2026-11-26T22:59:00Z"),
    ]);
    expect(ids(open)).toEqual(["dated", "broken"]);
  });

  it("sets the completed Tasks apart in the server's order, whatever their dates", () => {
    const { open, done } = orderGroupTasks([
      task("done-2", "2026-12-01T22:59:00Z", "completed"),
      task("open", null, "in_progress"),
      task("done-1", "2026-11-01T22:59:00Z", "completed"),
    ]);
    expect(ids(open)).toEqual(["open"]);
    expect(ids(done)).toEqual(["done-2", "done-1"]);
  });

  it("does not change the list it is given", () => {
    const given = [task("b", null), task("a", "2026-11-26T22:59:00Z")];
    orderGroupTasks(given);
    expect(ids(given)).toEqual(["b", "a"]);
  });
});

describe("sharedTaskTags", () => {
  it("gives the tags every Task has", () => {
    expect(
      sharedTaskTags([
        task("a", null, "todo", ["kund", "q4"]),
        task("b", null, "completed", ["q4", "kund", "extra"]),
      ]),
    ).toEqual(["kund", "q4"]);
  });

  it("gives nothing when one Task lacks the tag, has no tags at all, or there is only one Task", () => {
    expect(
      sharedTaskTags([
        task("a", null, "todo", ["kund"]),
        task("b", null, "todo", ["q4"]),
      ]),
    ).toEqual([]);
    expect(
      sharedTaskTags([task("a", null, "todo", ["kund"]), task("b", null)]),
    ).toEqual([]);
    expect(sharedTaskTags([task("a", null, "todo", ["kund"])])).toEqual([]);
    expect(sharedTaskTags([])).toEqual([]);
  });
});
