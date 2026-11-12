import { afterEach, describe, expect, it } from "vitest";

import { ownerEndOfDay } from "@/features/mcp-apps/ui/due";
import {
  changedFields,
  dateInputValue,
  draftFromTask,
  dueAtFromDateInput,
} from "@/features/work-app/tasks/task-edit";
import type { WorkTask } from "@/features/work-app/transport/transport";

// The edit form and the project's new Task build due_at as 23:59 on the Stockholm
// day, whatever the browser's zone, and read the Stockholm day back, so an untouched field never changes the due.
describe("the due date field in Stockholm time", () => {
  const original = process.env.TZ;
  afterEach(() => {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  });

  const ZONES = [
    "America/New_York",
    "Asia/Tokyo",
    "Pacific/Auckland",
    "Europe/Stockholm",
  ] as const;

  describe.each(ZONES)("browser zone %s", (zone) => {
    it("saves the picked day as 23:59 Stockholm and shows the same day back", () => {
      process.env.TZ = zone;
      expect(dueAtFromDateInput("2026-11-10")).toBe("2026-11-10T22:59:00.000Z");
      expect(dueAtFromDateInput("2026-07-10")).toBe("2026-07-10T21:59:00.000Z");
      expect(dueAtFromDateInput("2026-11-10")).toBe(
        ownerEndOfDay("2026-11-10"),
      );
      expect(dateInputValue("2026-11-10T22:59:00.000Z")).toBe("2026-11-10");
      // A due written as midnight UTC (an older write) reads as the Stockholm day it falls on.
      expect(dateInputValue("2026-11-10T00:00:00Z")).toBe("2026-11-10");
      expect(dueAtFromDateInput("")).toBeNull();
    });

    it("leaves the due unchanged when the field is not touched", () => {
      process.env.TZ = zone;
      const task = {
        title: "Ring kunden",
        description: null,
        priority: null,
        due_at: "2026-11-10T22:59:00.000Z",
      } as unknown as WorkTask;
      const draft = draftFromTask(task);
      expect(draft.due).toBe("2026-11-10");
      expect(
        changedFields({ values: draft, base: draft, dueIncomplete: false }),
      ).not.toHaveProperty("due_at");
    });
  });
});
