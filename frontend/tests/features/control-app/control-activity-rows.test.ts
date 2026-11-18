import { describe, expect, it } from "vitest";

import {
  activityText,
  withoutRepeatedActivity,
} from "@/features/control-app/activity-rows";
import { controlEn, controlSv } from "@/features/control-app/labels";
import type { ActivityRecord } from "@/features/control-app/transport";

const TASK = "019f0000-0000-7000-8000-0000000003c1";

function entry(overrides: Partial<ActivityRecord> = {}): ActivityRecord {
  return {
    id: "a1",
    category: "task_create",
    source: "assistant",
    operation: "create_task",
    state: "applied",
    aggregate_type: "task",
    aggregate_id: TASK,
    summary: "Create task: Email Lisa",
    occurred_at: "2026-11-01T09:00:02Z",
    ...overrides,
  };
}

const changes = [{ id: TASK, occurred_at: "2026-11-01T09:00:00Z" }];

describe("withoutRepeatedActivity", () => {
  it("drops an entry for the same record close in time", () => {
    expect(withoutRepeatedActivity(changes, [entry()])).toEqual([]);
  });

  it("keeps an entry for another record", () => {
    const other = entry({ aggregate_id: "other" });
    expect(withoutRepeatedActivity(changes, [other])).toEqual([other]);
  });

  it("keeps an entry far from the change in time", () => {
    const late = entry({ occurred_at: "2026-11-01T09:00:06Z" });
    expect(withoutRepeatedActivity(changes, [late])).toEqual([late]);
  });

  it("keeps an AI entry even for the same record and time", () => {
    const ai = entry({ category: "ai_steps", operation: "plan_set" });
    expect(withoutRepeatedActivity(changes, [ai])).toEqual([ai]);
  });

  it("keeps an entry that does not name its record", () => {
    const bare = entry();
    delete bare.aggregate_id;
    expect(withoutRepeatedActivity(changes, [bare])).toEqual([bare]);
  });
});

describe("activityText", () => {
  it("words a task operation with the name in both languages", () => {
    const e = entry({ after_values: { title: "Ring Karin" } });
    expect(activityText(controlSv, e)).toBe("Uppgift skapad: Ring Karin");
    expect(activityText(controlEn as typeof controlSv, e)).toBe(
      "Task created: Ring Karin",
    );
  });

  it("uses the run state for a run operation", () => {
    const e = entry({
      operation: "run_reported",
      after_values: { state: "accepted", title: "Plan" },
    });
    expect(activityText(controlSv, e)).toBe("AI-steg godkänt: Plan");
  });

  it("falls back to the operation when a run has no state", () => {
    expect(activityText(controlSv, entry({ operation: "run_queued" }))).toBe(
      "AI-steg köat",
    );
  });

  it("falls back to the stored summary for an unknown operation", () => {
    expect(activityText(controlSv, entry({ operation: "reorder_steps" }))).toBe(
      "Create task: Email Lisa",
    );
  });
});
