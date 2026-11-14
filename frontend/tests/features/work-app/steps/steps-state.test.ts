import { describe, expect, it } from "vitest";

import {
  initialStepsState,
  stepsReducer,
  type ArchivedStep,
  type StepsAction,
  type StepsState,
} from "@/features/work-app/steps/steps-state";
import type { WorkStep } from "@/features/work-app/transport/transport";

function step(id: string, patch: Partial<WorkStep> = {}): WorkStep {
  return {
    id,
    title: `Step ${id}`,
    status: "todo",
    version: 1,
    ...patch,
  } as WorkStep;
}

function run(state: StepsState, ...actions: StepsAction[]): StepsState {
  return actions.reduce(stepsReducer, state);
}

const ready = run(initialStepsState, {
  type: "loaded",
  items: [step("a"), step("b"), step("c")],
  cursor: undefined,
  failed: false,
});

describe("stepsReducer: reading the list", () => {
  it("starts loading and becomes ready with the list, cursor and a clean paging state", () => {
    expect(initialStepsState.phase).toBe("loading");
    const state = run(initialStepsState, {
      type: "loaded",
      items: [step("a")],
      cursor: "next",
      failed: false,
    });
    expect(state).toMatchObject({
      phase: "ready",
      nextCursor: "next",
      more: "idle",
      refreshing: false,
    });
    expect(state.steps.map((item) => item.id)).toEqual(["a"]);
  });

  it("marks paging failed when a later page could not be read, keeping the pages read", () => {
    const state = run(initialStepsState, {
      type: "loaded",
      items: [step("a")],
      cursor: "next",
      failed: true,
    });
    expect(state.more).toBe("failed");
    expect(state.steps).toHaveLength(1);
  });

  it("tells a forbidden read from any other failure and ends a refresh", () => {
    const refreshing = run(ready, { type: "reload" });
    expect(refreshing.refreshing).toBe(true);
    expect(
      run(refreshing, { type: "loadFailed", forbidden: true }),
    ).toMatchObject({ phase: "forbidden", refreshing: false });
    expect(
      run(refreshing, { type: "loadFailed", forbidden: false }).phase,
    ).toBe("error");
  });

  it("reads again on reload and retry, each with a new attempt; only a retry shows loading", () => {
    const reloaded = run(
      { ...ready, notice: { kind: "conflict" } },
      { type: "reload" },
    );
    expect(reloaded).toMatchObject({
      phase: "ready",
      attempt: 1,
      notice: undefined,
    });
    const retried = run(
      initialStepsState,
      { type: "loadFailed", forbidden: false },
      { type: "retryLoad" },
    );
    expect(retried).toMatchObject({ phase: "loading", attempt: 1 });
  });
});

describe("stepsReducer: checking a Step", () => {
  it("holds the Step busy and clears the earlier status, notice and Undo", () => {
    const before: StepsState = {
      ...ready,
      status: "Moved",
      notice: { kind: "invalid" },
      stepUndo: { id: "a", title: "Step a", version: 2, done: true },
    };
    const state = run(before, { type: "checkStarted", id: "b" });
    expect(state).toMatchObject({
      busyId: "b",
      status: undefined,
      notice: undefined,
      stepUndo: undefined,
    });
    expect(run(state, { type: "checkSettled" }).busyId).toBeUndefined();
  });

  it("replaces the checked Step in place and sets and expires its Undo", () => {
    const done = step("b", { status: "completed", version: 2 });
    const checked = run(ready, { type: "checked", step: done });
    expect(checked.steps.map((item) => item.status)).toEqual([
      "todo",
      "completed",
      "todo",
    ]);
    const withUndo = run(checked, {
      type: "stepUndoSet",
      stepUndo: { id: "b", title: "Step b", version: 2, done: true },
    });
    expect(withUndo.stepUndo?.id).toBe("b");
    expect(
      run(withUndo, { type: "stepUndoSet", stepUndo: undefined }).stepUndo,
    ).toBeUndefined();
  });

  it("a Step that is gone raises the notice and reads the list again", () => {
    const state = run(ready, { type: "notFound" });
    expect(state).toMatchObject({
      notice: { kind: "notFound" },
      refreshing: true,
      attempt: 1,
    });
  });

  it("a failed write keeps the Step id for the retry", () => {
    const state = run(ready, {
      type: "noticed",
      notice: { kind: "failed", stepId: "b" },
    });
    expect(state.notice).toEqual({ kind: "failed", stepId: "b" });
  });
});

describe("stepsReducer: reorder, paging and adding", () => {
  it("takes the server's order, drops the cursor and sets the status line", () => {
    const state = run(
      { ...ready, nextCursor: "more" },
      {
        type: "reordered",
        items: [step("b"), step("a"), step("c")],
        status: "Step a is now 2 of 3",
      },
    );
    expect(state.steps.map((item) => item.id)).toEqual(["b", "a", "c"]);
    expect(state.nextCursor).toBeUndefined();
    expect(state.status).toBe("Step a is now 2 of 3");
  });

  it("appends a page without repeating Steps already held", () => {
    const state = run(
      { ...ready, nextCursor: "p2" },
      { type: "moreStarted" },
      {
        type: "moreLoaded",
        items: [step("c"), step("d")],
        cursor: undefined,
      },
    );
    expect(state.steps.map((item) => item.id)).toEqual(["a", "b", "c", "d"]);
    expect(state).toMatchObject({ more: "idle", nextCursor: undefined });
    expect(run(ready, { type: "moreFailed" }).more).toBe("failed");
  });

  it("appends a created Step once, at the end, with the status line", () => {
    const created = step("d");
    const state = run(
      ready,
      { type: "created", step: created, status: "Added" },
      { type: "created", step: created, status: "Added" },
    );
    expect(state.steps.map((item) => item.id)).toEqual(["a", "b", "c", "d"]);
    expect(state.status).toBe("Added");
  });
});

describe("stepsReducer: archive and restore", () => {
  const item: ArchivedStep = { id: "b", title: "Step b", version: 3, index: 1 };

  it("moves the archived Step out of the list into the archive and offers Undo", () => {
    const state = run(ready, { type: "archived", item });
    expect(state.steps.map((entry) => entry.id)).toEqual(["a", "c"]);
    expect(state.archived).toEqual([item]);
    expect(state.undo).toEqual(item);
  });

  it("a newer archive replaces the Undo line and keeps the earlier one archived", () => {
    const second: ArchivedStep = {
      id: "c",
      title: "Step c",
      version: 2,
      index: 1,
    };
    const state = run(
      ready,
      { type: "archived", item },
      { type: "archived", item: second },
    );
    expect(state.undo).toEqual(second);
    expect(state.archived.map((entry) => entry.id)).toEqual(["b", "c"]);
  });

  it("a restore leaves the archive, clears its own Undo line and reads the list again", () => {
    const archived = run(ready, { type: "archived", item });
    const state = run(archived, {
      type: "restored",
      item,
      status: "Restored",
    });
    expect(state).toMatchObject({
      archived: [],
      undo: undefined,
      status: "Restored",
      refreshing: true,
      attempt: archived.attempt + 1,
    });
  });

  it("restoring an older archived Step keeps the Undo line of the newer one", () => {
    const second: ArchivedStep = {
      id: "c",
      title: "Step c",
      version: 2,
      index: 1,
    };
    const state = run(
      ready,
      { type: "archived", item },
      { type: "archived", item: second },
      { type: "restored", item, status: "Restored" },
    );
    expect(state.undo).toEqual(second);
    expect(state.archived).toEqual([second]);
  });
});

describe("stepsReducer: starting a write", () => {
  it("clears the status line, the notice and the Undo line", () => {
    const state = run(
      {
        ...ready,
        status: "Moved",
        notice: { kind: "forbidden" },
        stepUndo: { id: "a", title: "Step a", version: 2, done: false },
      },
      { type: "writeStarted" },
    );
    expect(state).toMatchObject({
      status: undefined,
      notice: undefined,
      stepUndo: undefined,
    });
  });
});
