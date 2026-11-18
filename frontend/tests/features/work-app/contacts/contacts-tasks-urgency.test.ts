import { expect, it } from "vitest";

import { tasksByUrgency } from "@/features/work-app/contacts/contacts-sections";

it("lists overdue Tasks first, then later dates, then Tasks without a date, keeping the given order for equal dates", () => {
  const tasks = [
    { id: "later", due_at: "2026-11-22T08:00:00Z" },
    { id: "none-1", due_at: null },
    { id: "overdue", due_at: "2026-11-17T08:00:00Z" },
    { id: "today", due_at: "2026-11-18T08:00:00Z" },
    { id: "none-2" },
    { id: "today-2", due_at: "2026-11-18T08:00:00Z" },
  ];

  expect(tasksByUrgency(tasks).map((task) => task.id)).toEqual([
    "overdue",
    "today",
    "today-2",
    "later",
    "none-1",
    "none-2",
  ]);
  // The given list is not changed.
  expect(tasks[0]?.id).toBe("later");
});
