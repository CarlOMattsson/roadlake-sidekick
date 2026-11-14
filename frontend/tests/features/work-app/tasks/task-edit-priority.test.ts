import { describe, expect, it } from "vitest";

import {
  changedFields,
  type TaskDraft,
} from "@/features/work-app/tasks/task-edit";

const base: TaskDraft = {
  title: "Ring kunden",
  description: "",
  priority: "normal",
  due: "",
};

function changesFor(values: Partial<TaskDraft>, from: TaskDraft = base) {
  return changedFields({
    values: { ...from, ...values },
    base: from,
    dueIncomplete: false,
  });
}

// update_task takes low, normal and high. A Task the server returns as urgent keeps that value in
// the form, but the app never sends it back.
describe("the priority field of the Task editor", () => {
  it.each(["low", "high"])("sends %s when the owner picks it", (priority) => {
    expect(changesFor({ priority })).toEqual({ priority });
  });

  it("sends nothing while the priority is untouched", () => {
    expect(changesFor({})).toEqual({});
  });

  it("does not send a value the tool does not accept", () => {
    expect(changesFor({ priority: "urgent" })).toEqual({});
  });

  it("sends the owner's pick for a Task that arrived as urgent, and nothing when it stays urgent", () => {
    const urgent = { ...base, priority: "urgent" };
    expect(changesFor({ priority: "high" }, urgent)).toEqual({
      priority: "high",
    });
    expect(changesFor({}, urgent)).toEqual({});
  });
});
