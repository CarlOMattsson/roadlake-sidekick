import { expect, it } from "vitest";
import {
  CONTROL_PARENT,
  canGoBack,
  createNavState,
  goBack,
  type NavEntry,
  type NavState,
  pushEntry,
  ROOT_VIEW,
  STACK_LIMIT,
  switchRoom,
  topOf,
} from "@/features/mcp-apps/nav-state";
import { ROOM_IDS } from "@/features/mcp-apps/router";

const entry = (id: string): NavEntry => ({
  room: "journal",
  view: "entry",
  id,
});
const contact = (id: string): NavEntry => ({
  room: "contacts",
  view: "contact",
  id,
});
const task = (id: string): NavEntry => ({ room: "work", view: "task", id });

function journalDay(): NavState {
  return createNavState({ room: "journal", view: "day" });
}

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

// Rule 1: the start entry is the root of its room; the other rooms get a plain root.
it("createNavState makes the start entry the active room's root", () => {
  const start: NavEntry = { room: "journal", view: "day" };
  const state = createNavState(start);
  expect(state.active).toBe("journal");
  expect(state.roots.journal).toEqual(start);
  for (const room of ROOM_IDS.filter((r) => r !== "journal"))
    expect(state.roots[room]).toEqual({ room, view: ROOT_VIEW });
  for (const room of ROOM_IDS) expect(state.stacks[room]).toEqual([]);
  expect(state.visited).toEqual(["journal"]);
});

// Rule 2: switching changes the active room, visits are recorded once, other stacks stay.
it("switchRoom changes the active room and records each visit once", () => {
  let state = journalDay();
  state = switchRoom(state, "work");
  expect(state.active).toBe("work");
  expect(state.visited).toEqual(["journal", "work"]);
  state = switchRoom(state, "journal");
  state = switchRoom(state, "work");
  expect(state.visited).toEqual(["journal", "work"]);
});

it("switchRoom leaves the old room's stack untouched", () => {
  let state = pushEntry(journalDay(), entry("e2"));
  const journalStack = state.stacks.journal;
  state = switchRoom(state, "shopping");
  expect(state.stacks.journal).toBe(journalStack);
  state = switchRoom(state, "journal");
  expect(state.stacks.journal).toEqual([entry("e2")]);
});

// Rule 3: pressing the active room goes to its root.
it("switchRoom to the active room empties its stack", () => {
  let state = pushEntry(journalDay(), contact("c1"));
  state = switchRoom(state, "journal");
  expect(state.active).toBe("journal");
  expect(state.stacks.journal).toEqual([]);
  expect(topOf(state, "journal")).toEqual({ room: "journal", view: "day" });
});

it("switchRoom to the active room with an empty stack returns the same state", () => {
  const state = journalDay();
  expect(switchRoom(state, "journal")).toBe(state);
});

// Rule 4: the entry goes on the active room's stack, whatever room the entry names.
it("pushEntry puts a foreign-room entry on the active room's stack", () => {
  const state = journalDay();
  const next = pushEntry(state, contact("c1"));
  expect(next.stacks.journal).toEqual([contact("c1")]);
  expect(next.stacks.contacts).toEqual([]);
  expect(next.active).toBe("journal");
  expect(topOf(next, "journal")).toEqual(contact("c1"));
});

// Rule 5: no duplicate of the top, the root, or labels and data differing only.
it("pushEntry ignores the same place twice in a row", () => {
  const state = pushEntry(journalDay(), contact("c1"));
  expect(pushEntry(state, contact("c1"))).toBe(state);
});

it("pushEntry treats entries differing only in label or data as the same place", () => {
  const state = pushEntry(journalDay(), {
    room: "contacts",
    view: "contact",
    id: "c1",
    label: "Anna",
  });
  expect(
    pushEntry(state, {
      room: "contacts",
      view: "contact",
      id: "c1",
      label: "Anna Svensson",
      data: { x: 1 },
    }),
  ).toBe(state);
});

it("pushEntry ignores the root's place when the stack is empty", () => {
  const state = createNavState(entry("e1"));
  expect(pushEntry(state, entry("e1"))).toBe(state);
});

it("pushEntry cuts the stack back to a place that is already in it (A, B, A is A)", () => {
  let state = pushEntry(journalDay(), contact("c1"));
  state = pushEntry(state, task("t1"));
  state = pushEntry(state, contact("c1"));
  expect(state.stacks.journal.map((e) => e.id)).toEqual(["c1"]);
});

it("pushEntry with replace swaps the top layer, and pushes when the stack is empty", () => {
  let state = pushEntry(journalDay(), entry("d1"));
  state = pushEntry(state, entry("e2"), { replace: true });
  expect(state.stacks.journal.map((e) => e.id)).toEqual(["e2"]);
  const empty = pushEntry(journalDay(), entry("e3"), { replace: true });
  expect(empty.stacks.journal.map((e) => e.id)).toEqual(["e3"]);
});

it("a card that opens on one record makes the room's overview the root and the record its first step", () => {
  const state = createNavState(entry("e1"));
  expect(state.roots.journal).toEqual({ room: "journal", view: "root" });
  expect(state.stacks.journal).toEqual([entry("e1")]);
  expect(canGoBack(state)).toBe(true);
  expect(topOf(goBack(state), "journal").view).toBe("root");
  // A list is its room's root as before.
  const day = createNavState({ room: "journal", view: "day" });
  expect(day.roots.journal.view).toBe("day");
  expect(canGoBack(day)).toBe(false);
  for (const start of [
    { room: "work" as const, view: "task", id: "t1" },
    { room: "work" as const, view: "project", id: "p1" },
    { room: "contacts" as const, view: "contact", id: "c1" },
    { room: "contacts" as const, view: "compact" },
  ])
    expect(createNavState(start).stacks[start.room]).toEqual([start]);
});

// Control opened by Claude is a step of Arbete: Arbete is active and its overview the root, Control the first step.
// Back then leads to Arbete's root, and a press on Arbete in the strip empties the stack.
it("a card that opens on Control makes Arbete active, with its overview as root and Control as the first step", () => {
  const start: NavEntry = { room: "control", view: "trash" };
  const state = createNavState(start);
  expect(CONTROL_PARENT).toBe("work");
  expect(state.active).toBe(CONTROL_PARENT);
  expect(state.roots.work).toEqual({ room: "work", view: ROOT_VIEW });
  expect(state.stacks.work).toEqual([start]);
  expect(state.stacks.control).toEqual([]);
  expect(state.visited).toEqual(["work"]);
  expect(canGoBack(state)).toBe(true);
  expect(topOf(goBack(state), "work")).toEqual({
    room: "work",
    view: ROOT_VIEW,
  });
  const pressedWork = switchRoom(state, "work");
  expect(pressedWork.stacks.work).toEqual([]);
  expect(canGoBack(pressedWork)).toBe(false);
});

// Rule 6: the limit drops the oldest entry and keeps the newest ones in order.
it("pushEntry keeps at most STACK_LIMIT entries and drops the oldest", () => {
  let state = journalDay();
  for (let i = 1; i <= 10; i++) state = pushEntry(state, entry(`e${i}`));
  expect(STACK_LIMIT).toBe(8);
  expect(state.stacks.journal).toHaveLength(STACK_LIMIT);
  expect(state.stacks.journal.map((e) => e.id)).toEqual([
    "e3",
    "e4",
    "e5",
    "e6",
    "e7",
    "e8",
    "e9",
    "e10",
  ]);
});

// Rule 7: Back pops the active room's top only.
it("goBack removes the top entry of the active room", () => {
  let state = pushEntry(journalDay(), contact("c1"));
  state = pushEntry(state, task("t1"));
  state = goBack(state);
  expect(topOf(state, "journal")).toEqual(contact("c1"));
  expect(state.stacks.journal).toHaveLength(1);
});

it("canGoBack is false on an empty stack and goBack returns the same state", () => {
  const state = journalDay();
  expect(canGoBack(state)).toBe(false);
  expect(goBack(state)).toBe(state);
});

it("goBack does not touch the stacks of other rooms", () => {
  let state = pushEntry(journalDay(), entry("e2"));
  state = switchRoom(state, "contacts");
  state = pushEntry(state, contact("c1"));
  state = switchRoom(state, "journal");
  const contactsStack = state.stacks.contacts;
  state = goBack(state);
  expect(state.stacks.journal).toEqual([]);
  expect(state.stacks.contacts).toBe(contactsStack);
  expect(state.stacks.contacts).toEqual([contact("c1")]);
});

// Rule 8: the journal strip walks back through a chain of cross-links.
it("Back walks a cross-link chain from the task to the journal entry", () => {
  let state = createNavState(entry("e1"));
  state = pushEntry(state, contact("c1"));
  state = pushEntry(state, task("t1"));
  expect(state.active).toBe("journal");
  state = goBack(state);
  expect(state.active).toBe("journal");
  expect(topOf(state, "journal")).toEqual(contact("c1"));
  state = goBack(state);
  expect(state.active).toBe("journal");
  expect(topOf(state, "journal")).toEqual(entry("e1"));
  // The entry is a first step above the journal's overview: one more Back reaches the day.
  expect(canGoBack(state)).toBe(true);
  state = goBack(state);
  expect(topOf(state, "journal").view).toBe("root");
  expect(canGoBack(state)).toBe(false);
});

// Rule 9: the functions are pure; a frozen input must not throw and must not change.
it("never mutates the state it is given", () => {
  const state = deepFreeze(
    pushEntry(journalDay(), {
      room: "work",
      view: "task",
      id: "t2",
      data: { task: { id: "t2" } },
    }),
  );
  const before = JSON.stringify(state);
  const results: NavState[] = [
    switchRoom(state, "work"),
    switchRoom(state, "journal"),
    pushEntry(state, task("t1")),
    pushEntry(state, contact("c1")),
    goBack(state),
  ];
  expect(results).toHaveLength(5);
  expect(canGoBack(state)).toBe(true);
  expect(topOf(state, "journal").id).toBe("t2");
  expect(JSON.stringify(state)).toBe(before);
});
