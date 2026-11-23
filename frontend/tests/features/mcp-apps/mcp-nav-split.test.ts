import { describe, expect, it } from "vitest";
import {
  closeBeside,
  createNavState,
  openBeside,
  pushEntry,
  splitOf,
  switchRoom,
  topOf,
  type NavEntry,
  type NavState,
} from "@/features/mcp-apps/nav-state";
import {
  createShellNavState,
  shellNavReducer,
} from "@/features/mcp-apps/shell-nav-reducer";

// The split pane's rule and its two steps (desktop spec 2.1): which list a record opens beside in a wide frame, and how
// stepping through that list swaps the record without building a stack.

const task = (id: string): NavEntry => ({ room: "work", view: "task", id });
const contact = (id: string): NavEntry => ({
  room: "contacts",
  view: "contact",
  id,
});
const entry = (id: string): NavEntry => ({
  room: "journal",
  view: "entry",
  id,
});
const wide = { wide: true };

function work(view = "agenda"): NavState {
  return createNavState({ room: "work", view });
}

describe("splitOf", () => {
  it("draws every pane alone below 64rem, whatever is open", () => {
    const opened = pushEntry(work(), task("t1"));
    expect(splitOf(opened, "work", { wide: false })).toEqual({
      kind: "single",
    });
    expect(splitOf(work(), "work", { wide: false })).toEqual({
      kind: "single",
    });
  });

  it("puts the aside beside a list with nothing open", () => {
    expect(splitOf(work(), "work", wide)).toEqual({ kind: "aside", list: 0 });
    const contacts = createNavState({ room: "contacts", view: "list" });
    expect(splitOf(contacts, "contacts", wide)).toEqual({
      kind: "aside",
      list: 0,
    });
    const day = createNavState({ room: "journal", view: "day" });
    expect(splitOf(day, "journal", wide)).toEqual({ kind: "aside", list: 0 });
  });

  it("splits Start's suggestions the same way: the inbox beside one suggestion", () => {
    const inbox = createNavState({ room: "start", view: "root" });
    expect(splitOf(inbox, "start", wide)).toEqual({ kind: "aside", list: 0 });
    const listed = createNavState({ room: "start", view: "suggestions" });
    expect(splitOf(listed, "start", wide)).toEqual({ kind: "aside", list: 0 });
    const opened = pushEntry(inbox, {
      room: "start",
      view: "suggestion",
      id: "s1",
    });
    expect(splitOf(opened, "start", wide)).toEqual({
      kind: "split",
      list: 0,
      detail: 1,
    });
    expect(splitOf(opened, "start", { wide: false })).toEqual({
      kind: "single",
    });
  });

  it("opens a record beside the list it came from", () => {
    expect(splitOf(pushEntry(work(), task("t1")), "work", wide)).toEqual({
      kind: "split",
      list: 0,
      detail: 1,
    });
  });

  it("keeps the list beside a record opened from the record (Task, then its Contact)", () => {
    const deeper = pushEntry(pushEntry(work(), task("t1")), contact("c1"));
    expect(splitOf(deeper, "work", wide)).toEqual({
      kind: "split",
      list: 0,
      detail: 2,
    });
  });

  it("opens a record over a wide view as a drawer, by the view or by what the list said", () => {
    const board = pushEntry(work("board"), task("t1"));
    expect(splitOf(board, "work", wide)).toEqual({
      kind: "drawer",
      list: 0,
      detail: 1,
    });
    // Work's Agenda root that switched to its Status tab.
    const switched = pushEntry(work(), task("t1"));
    expect(
      splitOf(switched, "work", { wide: true, layouts: { 0: "wide" } }),
    ).toEqual({ kind: "drawer", list: 0, detail: 1 });
    // And a board root on its Agenda tab is a column again.
    expect(
      splitOf(board, "work", { wide: true, layouts: { 0: "list" } }),
    ).toEqual({
      kind: "split",
      list: 0,
      detail: 1,
    });
  });

  it("draws a wide view with nothing open alone: no aside beside the board", () => {
    expect(splitOf(work("board"), "work", wide)).toEqual({ kind: "single" });
  });

  it("does not split under a layer that is no list: Control, Shopping, the Journal's pending", () => {
    const control = pushEntry(work(), { room: "control", view: "trash" });
    expect(splitOf(control, "work", wide)).toEqual({ kind: "single" });
    expect(splitOf(pushEntry(control, task("t1")), "work", wide)).toEqual({
      kind: "single",
    });
    const shopping = createNavState({ room: "shopping", view: "list" });
    expect(splitOf(shopping, "shopping", wide)).toEqual({ kind: "single" });
    const pending = createNavState({ room: "journal", view: "pending" });
    expect(splitOf(pending, "journal", wide)).toEqual({ kind: "single" });
  });

  it("splits a card that opened straight on a record: the room's overview is the list", () => {
    const card = createNavState(task("t1"));
    expect(splitOf(card, "work", wide)).toEqual({
      kind: "split",
      list: 0,
      detail: 1,
    });
  });

  it("reads the room asked for, not the active one", () => {
    const state = switchRoom(pushEntry(work(), task("t1")), "journal");
    expect(splitOf(state, "work", wide).kind).toBe("split");
    expect(splitOf(state, "journal", wide)).toEqual({ kind: "aside", list: 0 });
  });
});

describe("openBeside and closeBeside", () => {
  it("opens the first record beside the list and swaps it for the next one: the stack's depth stays one", () => {
    const first = openBeside(work(), 0, task("t1"));
    expect(first.stacks.work).toEqual([task("t1")]);
    const next = openBeside(first, 0, task("t2"));
    expect(next.stacks.work).toEqual([task("t2")]);
    expect(topOf(next, "work")).toEqual(task("t2"));
  });

  it("drops the records the detail had opened above itself", () => {
    const deeper = pushEntry(pushEntry(work(), task("t1")), contact("c1"));
    expect(openBeside(deeper, 0, task("t2")).stacks.work).toEqual([task("t2")]);
  });

  it("changes nothing for the record already shown", () => {
    const first = openBeside(work(), 0, task("t1"));
    expect(openBeside(first, 0, task("t1"))).toBe(first);
  });

  it("keeps the layers under a list that is not the root", () => {
    const state = pushEntry(
      pushEntry(createNavState({ room: "journal", view: "day" }), entry("e1")),
      { room: "contacts", view: "list" },
    );
    const opened = openBeside(state, 2, contact("c1"));
    expect(opened.stacks.journal).toEqual([
      entry("e1"),
      { room: "contacts", view: "list" },
      contact("c1"),
    ]);
  });

  it("closes all that is open beside the list, and nothing when nothing is", () => {
    const deeper = pushEntry(pushEntry(work(), task("t1")), contact("c1"));
    expect(closeBeside(deeper, 0).stacks.work).toEqual([]);
    const none = work();
    expect(closeBeside(none, 0)).toBe(none);
  });
});

describe("the reducer's split steps", () => {
  it("marks a swap, not the first record opened beside the list, and forgets it on the next step", () => {
    const start = createShellNavState({ room: "work", view: "agenda" }, true);
    const first = shellNavReducer(start, {
      type: "beside",
      target: task("t1"),
      list: 0,
    });
    expect(first.swapped).toBe(false);
    const next = shellNavReducer(first, {
      type: "beside",
      target: task("t2"),
      list: 0,
    });
    expect(next.swapped).toBe(true);
    expect(next.nav.stacks.work).toEqual([task("t2")]);
    const closed = shellNavReducer(next, { type: "close-beside", list: 0 });
    expect(closed.swapped).toBe(false);
    expect(closed.nav.stacks.work).toEqual([]);
    expect(shellNavReducer(closed, { type: "close-beside", list: 0 })).toBe(
      closed,
    );
  });
});
