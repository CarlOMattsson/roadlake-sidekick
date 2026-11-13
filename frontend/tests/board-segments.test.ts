import { describe, expect, it } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  PROJECT_SEGMENT,
  boardSegments,
  defaultBoardSegment,
  nestSteps,
  segmentItems,
  type BoardSegment,
} from "@/features/work-app/shared/work-items";
import type {
  WorkBoardPage,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";

function record(kind: string, id: string, status: string): WorkItemRecord {
  return { kind, id, title: `${kind} ${id}`, status };
}

function page(columns: Record<string, WorkItemRecord[]>): WorkBoardPage {
  return { columns, next_cursor: null };
}

function segmentKeys(segments: BoardSegment[]): string[] {
  return segments.map((segment) => segment.key);
}

describe("boardSegments", () => {
  it("lists the four Task statuses in fixed order with Swedish labels and counts", () => {
    const segments = boardSegments(
      page({
        todo: [record("task", "a", "todo"), record("task", "b", "todo")],
        in_progress: [record("task", "c", "in_progress")],
        blocked: [],
        completed: [record("task", "d", "completed")],
      }),
      workSv,
    );
    expect(segmentKeys(segments)).toEqual([
      "todo",
      "in_progress",
      "blocked",
      "completed",
    ]);
    expect(segments.map((segment) => segment.label)).toEqual([
      "Att göra",
      "Pågår",
      "Blockerad",
      "Klar",
    ]);
    expect(segments.map((segment) => segment.count)).toEqual([2, 1, 0, 1]);
    expect(segments.map((segment) => segment.columns)).toEqual([
      ["todo"],
      ["in_progress"],
      ["blocked"],
      ["completed"],
    ]);
  });

  it("uses English labels for the English catalogue", () => {
    const segments = boardSegments(page({}), workEn);
    expect(segments.map((segment) => segment.label)).toEqual([
      "To do",
      "In progress",
      "Blocked",
      "Done",
    ]);
  });

  it("adds no Projects segment when the page holds no Project", () => {
    const segments = boardSegments(
      page({ todo: [record("task", "a", "todo")] }),
      workSv,
    );
    expect(segmentKeys(segments)).not.toContain(PROJECT_SEGMENT);
  });

  it("adds a Projects segment with the project columns and counts only the Projects", () => {
    const segments = boardSegments(
      page({
        todo: [record("task", "a", "todo")],
        active: [
          record("project", "p1", "active"),
          record("project", "p2", "active"),
        ],
        paused: [record("project", "p3", "paused")],
      }),
      workSv,
    );
    const projects = segments.find(
      (segment) => segment.key === PROJECT_SEGMENT,
    );
    expect(projects).toEqual({
      key: "project",
      label: "Projekt",
      count: 3,
      columns: ["active", "paused"],
    });
    expect(segments[segments.length - 1]).toBe(projects);
  });

  it("does not count a Project in the Task status column it shares a name with", () => {
    const segments = boardSegments(
      page({
        completed: [
          record("task", "t1", "completed"),
          record("project", "p1", "completed"),
        ],
      }),
      workSv,
    );
    const done = segments.find((segment) => segment.key === "completed");
    expect(done?.count).toBe(1);
    const projects = segments.find(
      (segment) => segment.key === PROJECT_SEGMENT,
    );
    expect(projects?.columns).toEqual(["completed"]);
    expect(projects?.count).toBe(1);
  });

  it("shows a Task in a column that is not a Task status in the Projects segment", () => {
    const segments = boardSegments(
      page({ someday: [record("task", "a", "someday")] }),
      workSv,
    );
    const projects = segments.find(
      (segment) => segment.key === PROJECT_SEGMENT,
    );
    expect(projects?.count).toBe(1);
    expect(projects?.columns).toEqual(["someday"]);
  });
});

describe("segmentItems", () => {
  it("keeps board order inside a Task status segment and leaves Projects out", () => {
    const items = page({
      completed: [
        record("task", "t1", "completed"),
        record("project", "p1", "completed"),
        record("task", "t2", "completed"),
      ],
    });
    const done = boardSegments(items, workSv).find(
      (segment) => segment.key === "completed",
    );
    expect(done).toBeDefined();
    expect(segmentItems(items, done!).map((item) => item.id)).toEqual([
      "t1",
      "t2",
    ]);
  });

  it("lists Projects and non-status records in column order for the Projects segment", () => {
    const items = page({
      todo: [record("task", "t1", "todo")],
      active: [record("project", "p1", "active")],
      paused: [record("project", "p2", "paused")],
    });
    const projects = boardSegments(items, workSv).find(
      (segment) => segment.key === PROJECT_SEGMENT,
    );
    expect(projects).toBeDefined();
    expect(segmentItems(items, projects!).map((item) => item.id)).toEqual([
      "p1",
      "p2",
    ]);
  });
});

describe("defaultBoardSegment", () => {
  const withCounts = (counts: Record<string, number>): BoardSegment[] =>
    ["todo", "in_progress", "blocked", "completed"].map((key) => ({
      key,
      label: key,
      count: counts[key] ?? 0,
      columns: [key],
    }));

  it("opens the saved column when a segment shows it, even when that segment is empty", () => {
    const segments = withCounts({ todo: 2, in_progress: 0 });
    expect(defaultBoardSegment(segments, "in_progress")).toBe("in_progress");
  });

  it("maps a saved column to the segment that shows it", () => {
    const segments: BoardSegment[] = [
      ...withCounts({ todo: 1 }),
      { key: PROJECT_SEGMENT, label: "Projekt", count: 1, columns: ["active"] },
    ];
    expect(defaultBoardSegment(segments, "active")).toBe(PROJECT_SEGMENT);
  });

  it("falls back to the first non-empty of To do, In progress and Blocked", () => {
    expect(
      defaultBoardSegment(withCounts({ in_progress: 1, blocked: 1 })),
    ).toBe("in_progress");
    expect(defaultBoardSegment(withCounts({ blocked: 2, completed: 5 }))).toBe(
      "blocked",
    );
  });

  it("falls back to To do when every segment is empty or the saved column is unknown", () => {
    expect(defaultBoardSegment(withCounts({ completed: 3 }))).toBe("todo");
    expect(defaultBoardSegment(withCounts({ blocked: 1 }), "nonexistent")).toBe(
      "blocked",
    );
  });
});

describe("board segment labels", () => {
  it("have Swedish and English texts for the single-column board", () => {
    expect(workSv.moveUp).toBe("Flytta upp");
    expect(workSv.moveDown).toBe("Flytta ned");
    expect(workEn.moveUp).toBe("Move up");
    expect(workEn.moveDown).toBe("Move down");
    expect(workSv.moreActions).toBe("Fler val");
    expect(workEn.moreActions).toBe("More options");
  });

  it("names the quick choices of a card with the long-press hint, in Swedish and English", () => {
    expect(workSv.rowMenuHint).toBe("Håll inne en uppgift för fler val.");
    expect(workEn.rowMenuHint).toBe("Touch and hold a task for more options.");
  });
});

/** A Step whose Task is `taskId`. */
function step(id: string, taskId: string): WorkItemRecord {
  return {
    kind: "step",
    id,
    title: `step ${id}`,
    status: "todo",
    task_id: taskId,
  };
}

describe("nestSteps", () => {
  it("stands a Step right after its Task, when the Step came before it", () => {
    const items = [
      step("s1", "t1"),
      record("task", "t1", "todo"),
      record("task", "t2", "todo"),
    ];
    expect(nestSteps(items).map((i) => i.id)).toEqual(["t1", "s1", "t2"]);
  });

  it("keeps the order of several Steps under one Task, after the Task's earlier Steps", () => {
    const items = [
      record("task", "t2", "todo"),
      step("sA", "t1"),
      record("task", "t1", "todo"),
      step("sB", "t1"),
      step("sC", "t2"),
    ];
    expect(nestSteps(items).map((i) => i.id)).toEqual([
      "t2",
      "sC",
      "t1",
      "sA",
      "sB",
    ]);
  });

  it("keeps a Step in its place when its Task is not on the list", () => {
    const items = [
      step("sX", "tX"),
      record("task", "t1", "todo"),
      step("s1", "tY"),
    ];
    expect(nestSteps(items).map((i) => i.id)).toEqual(["sX", "t1", "s1"]);
  });

  it("leaves the order of the Tasks as it is, and returns the same records", () => {
    const items = [
      record("task", "t3", "in_progress"),
      record("task", "t1", "todo"),
      record("task", "t2", "completed"),
    ];
    const nested = nestSteps(items);
    expect(nested.map((i) => i.id)).toEqual(["t3", "t1", "t2"]);
    expect(nested[0]).toBe(items[0]);
  });
});
