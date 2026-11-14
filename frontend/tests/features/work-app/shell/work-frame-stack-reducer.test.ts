import { describe, expect, it } from "vitest";
import {
  createFrameStackState,
  frameStackReducer,
  type FrameStackAction,
} from "@/features/work-app/view/parts/frame-stack-reducer";
import {
  workTabsReducer,
  createWorkTabsState,
} from "@/features/work-app/shell/work-shell-tabs";
import type { WorkFrame } from "@/features/work-app/transport/transport";

const board = (name: string) =>
  ({ kind: "board", name }) as unknown as WorkFrame;
const task = (id: string): WorkFrame => ({ kind: "task", id });
const contact = (id: string): WorkFrame => ({ kind: "contact", id });

function run(
  state: ReturnType<typeof createFrameStackState>,
  ...actions: FrameStackAction[]
) {
  return actions.reduce(frameStackReducer, state);
}

describe("frame stack reducer", () => {
  it("starts with the initial frame, or an empty stack", () => {
    expect(createFrameStackState(task("1")).stack).toEqual([task("1")]);
    expect(createFrameStackState(undefined).stack).toEqual([]);
  });

  it("counts every push and pop as a move", () => {
    const state = run(
      createFrameStackState(board("a")),
      { type: "push", frame: task("1") },
      { type: "back" },
    );
    expect(state.stack).toEqual([board("a")]);
    expect(state.moves).toBe(2);
  });

  it("never pops the root, but still counts the move", () => {
    const start = createFrameStackState(board("a"));
    const state = run(start, { type: "back" });
    expect(state.stack).toBe(start.stack);
    expect(state.moves).toBe(1);
  });

  it("opens a Contact in its editor only until another frame is pushed", () => {
    let state = run(createFrameStackState(board("a")), {
      type: "push",
      frame: contact("c1"),
      edit: true,
    });
    expect(state.editContactId).toBe("c1");
    state = run(state, { type: "push", frame: task("1") });
    expect(state.editContactId).toBeUndefined();
  });

  it("does not open a non-Contact frame in an editor", () => {
    const state = run(createFrameStackState(undefined), {
      type: "push",
      frame: task("1"),
      edit: true,
    });
    expect(state.editContactId).toBeUndefined();
  });

  it("re-roots on a new initial: a new session, no moves, not stale", () => {
    let state = run(
      createFrameStackState(board("a")),
      { type: "push", frame: task("1") },
      { type: "stale", stale: true },
    );
    state = run(state, { type: "reset", initial: board("b") });
    expect(state).toMatchObject({
      stack: [board("b")],
      seen: board("b"),
      session: 1,
      moves: 0,
      stale: false,
    });
  });

  it("replaces a frame wherever it sits in the stack", () => {
    const before = board("a");
    const after = board("a2");
    const state = run(
      createFrameStackState(before),
      { type: "push", frame: task("1") },
      { type: "replace", before, after },
    );
    expect(state.stack).toEqual([after, task("1")]);
  });

  it("lets a second patch from the same batch replace the top frame of its kind", () => {
    const before = board("a");
    const state = run(
      createFrameStackState(before),
      { type: "replace", before, after: board("first") },
      { type: "replace", before, after: board("second") },
    );
    expect(state.stack).toEqual([board("second")]);
  });

  it("drops a patch that matches nothing, and keeps the state identical", () => {
    const state = createFrameStackState(task("1"));
    expect(
      run(state, { type: "replace", before: board("x"), after: board("y") }),
    ).toBe(state);
  });

  it("does not change on a repeated stale flag", () => {
    const state = run(createFrameStackState(undefined), {
      type: "stale",
      stale: true,
    });
    expect(run(state, { type: "stale", stale: true })).toBe(state);
  });
});

describe("work shell tabs reducer", () => {
  it("mounts only the tab shown at first", () => {
    const state = createWorkTabsState("agenda");
    expect([...state.visited]).toEqual(["agenda"]);
  });

  it("marks a tab visited when it is pressed, and keeps it", () => {
    let state = workTabsReducer(createWorkTabsState("agenda"), {
      type: "choose",
      tab: "board",
    });
    state = workTabsReducer(state, { type: "choose", tab: "agenda" });
    expect(state.tab).toBe("agenda");
    expect([...state.visited]).toEqual(["agenda", "board"]);
  });

  it("returns the same state when the shown tab is pressed again", () => {
    const state = createWorkTabsState("board");
    expect(workTabsReducer(state, { type: "choose", tab: "board" })).toBe(
      state,
    );
  });
});
