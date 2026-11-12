import { describe, expect, it } from "vitest";
import { topOf, type NavEntry } from "@/features/mcp-apps/nav-state";
import {
  answerProps,
  createShellNavState,
  shellNavReducer,
  type ShellNavState,
} from "@/features/mcp-apps/shell-nav-reducer";

const day: NavEntry = { room: "journal", view: "day" };
const agenda: NavEntry = { room: "work", view: "agenda" };
const entry = (id: string): NavEntry => ({
  room: "journal",
  view: "entry",
  id,
});

function run(
  state: ShellNavState,
  ...actions: Parameters<typeof shellNavReducer>[1][]
) {
  return actions.reduce(shellNavReducer, state);
}

describe("shell navigation reducer", () => {
  it("starts on the card's own entry, not yet answering any openAt", () => {
    const state = createShellNavState(day, false);
    expect(state.nav.active).toBe("journal");
    expect(topOf(state.nav, "journal")).toBe(day);
    expect(state.pushedOpenAt).toBeUndefined();
    expect(state.wasFull).toBe(false);
  });

  it("answers props once and then has nothing left to answer", () => {
    const props = { start: day, openAt: entry("a"), full: true };
    const first = createShellNavState(day, true);
    const answered = shellNavReducer(first, { type: "props", ...props });
    expect(topOf(answered.nav, "journal")).toEqual(entry("a"));
    expect(answerProps(answered, props)).toBe(answered);
  });

  it("starts the full view from the card's entry, not the room last visited", () => {
    let state = createShellNavState(day, false);
    state = run(
      state,
      { type: "props", start: day, full: true },
      { type: "push", target: entry("a") },
      { type: "switch-room", room: "work" },
      { type: "props", start: day, full: false },
      { type: "props", start: day, full: true },
    );
    expect(state.nav.active).toBe("journal");
    expect(state.nav.stacks.journal).toEqual([]);
    expect(state.nav.visited).toEqual(["journal"]);
  });

  it("pushes a changed openAt on the current stacks, and a cleared one pushes nothing", () => {
    let state = createShellNavState(day, true);
    state = run(state, { type: "props", start: day, full: true });
    state = run(state, {
      type: "props",
      start: day,
      openAt: entry("a"),
      full: true,
    });
    expect(state.nav.stacks.journal).toEqual([entry("a")]);
    state = run(state, { type: "props", start: day, full: true });
    expect(state.pushedOpenAt).toBeUndefined();
    expect(state.nav.stacks.journal).toEqual([entry("a")]);
  });

  it("roots the stacks again on a new tool result", () => {
    let state = createShellNavState(day, true);
    state = run(state, { type: "push", target: entry("a") });
    const next: NavEntry = { room: "journal", view: "day", resultId: 2 };
    state = run(state, { type: "props", start: next, full: true });
    expect(state.nav.stacks.journal).toEqual([]);
    expect(topOf(state.nav, "journal")).toBe(next);
    expect(state.seenStart).toBe(next);
  });

  it("mounts the card again when the full view touched its domain", () => {
    let state = createShellNavState(day, true);
    state = run(state, { type: "inline-stale" }, { type: "inline-stale" });
    expect(state.inlineStale).toBe(true);
    state = run(state, { type: "props", start: day, full: false });
    expect(state).toMatchObject({ inlineStale: false, inlineKey: 1 });
  });

  it("keeps the card as it was when the full view wrote nothing", () => {
    let state = createShellNavState(day, true);
    state = run(state, { type: "props", start: day, full: false });
    expect(state.inlineKey).toBe(0);
  });

  it("moves between rooms and back, one step at a time", () => {
    let state = createShellNavState(agenda, true);
    state = run(
      state,
      { type: "switch-room", room: "journal" },
      { type: "push", target: entry("a") },
    );
    expect(state.nav.active).toBe("journal");
    expect(state.nav.stacks.journal).toEqual([entry("a")]);
    state = run(state, { type: "back" });
    expect(state.nav.stacks.journal).toEqual([]);
  });

  it("replaces the top layer when asked", () => {
    let state = createShellNavState(day, true);
    state = run(
      state,
      { type: "push", target: entry("draft") },
      { type: "push", target: entry("saved"), replace: true },
    );
    expect(state.nav.stacks.journal).toEqual([entry("saved")]);
  });

  it("returns the same state when an action changes nothing", () => {
    const state = createShellNavState(day, true);
    expect(shellNavReducer(state, { type: "back" })).toBe(state);
    expect(
      shellNavReducer(state, { type: "switch-room", room: "journal" }),
    ).toBe(state);
    expect(shellNavReducer(state, { type: "push", target: day })).toBe(state);
  });
});
