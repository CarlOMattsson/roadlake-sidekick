/**
 * Navigation state of the Sidekick shell, as pure functions (no React), so the rules in the design
 * (docs/explanation/architecture/mcp-apps.md, "Entry, navigation and durable context") can be tested one by one.
 *
 * One stack per room. A cross-link pushes its target on the stack of the room the user is in, so the
 * strip keeps showing that room. Back pops the top. Pressing the active room returns to its root.
 * There is no window.history: the state lives in memory only.
 */
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";
import type { ToolArgs } from "@/features/mcp-apps/room-types";

/** At most this many entries sit above a room's root; pushing one more drops the oldest. */
export const STACK_LIMIT = 8;
/** The view of a room that was not opened by a tool result: the room shows its own home. */
export const ROOT_VIEW = "root";

/**
 * Something a room can show. `room` says which room's component draws it, which is not always the
 * room whose stack holds it: a contact reached from the journal sits in the journal's stack.
 * `id` is the record id when the view is a record. `label` is a short name for the model context;
 * never journal text. `data` is the tool result that opened the entry, when there was one, and
 * `isError` says that result was an error (then `data` is its structuredContent, often absent).
 */
export type NavEntry = {
  room: RoomId;
  view: string;
  id?: string;
  label?: string;
  /** The list view this entry was opened from ("agenda", "board", "hierarchy"); Back names it when the entry below is a list. */
  from?: string;
  data?: unknown;
  isError?: boolean;
  /** With an error result: the tool and record id of the call, so the room can read that again. */
  toolArgs?: ToolArgs;
  /** Counts the tool results of the card; a room treats a changed count as a new result (two empty errors in a row). */
  resultId?: number;
};

export type NavState = {
  /** The room the user is in; its pane is the one shown. */
  active: RoomId;
  /** What each room shows when its stack is empty. */
  roots: Record<RoomId, NavEntry>;
  /** Entries above the root, oldest first. */
  stacks: Record<RoomId, NavEntry[]>;
  /** Rooms that have been shown at least once; only these are mounted. */
  visited: RoomId[];
};

function perRoom<T>(make: (room: RoomId) => T): Record<RoomId, T> {
  return Object.fromEntries(
    ROOM_IDS.map((room) => [room, make(room)]),
  ) as Record<RoomId, T>;
}

/** The views that show one record (a Task, a Contact, a post). They are details, never a room's overview. */
const RECORD_VIEWS: Readonly<Record<string, readonly string[]>> = {
  start: ["suggestion"],
  work: ["task", "project", "process"],
  contacts: ["contact", "compact"],
  journal: ["entry", "draft", "card", "source"],
};

/** True when `entry` shows one record rather than a room's overview. */
export function isRecordEntry(entry: NavEntry): boolean {
  return RECORD_VIEWS[entry.room]?.includes(entry.view) === true;
}

/**
 * The room Control is a step of when Claude opened it directly (designsystem §4, Kontrolls navigering). From a
 * room's ⋯ Control is pushed on that room's stack instead, so Back returns to the room the user came from. The strip
 * marks no room while Control is on top (designsystem §3).
 */
export const CONTROL_PARENT: RoomId = "work";

/**
 * The card opened on `start`: that room is active and is the only one mounted. A list or overview
 * (agenda, board, day, shopping list) is the room's root. A card that opened straight on one record
 * (a Task, a post, a Contact) makes the room's overview the root and the record its first step, so
 * Back and a press on the room always reach the overview.
 * Control is never a root: it is a step above Work's overview, so the strip marks no room and Back
 * reads the Back row to the room.
 */
export function createNavState(start: NavEntry): NavState {
  const home = start.room === "control" ? CONTROL_PARENT : start.room;
  const step = home !== start.room || isRecordEntry(start);
  return {
    active: home,
    roots: perRoom((room) =>
      room === home && !step ? start : { room, view: ROOT_VIEW },
    ),
    stacks: perRoom((room) => (room === home && step ? [start] : [])),
    visited: [home],
  };
}

/** What a room shows now: the top of its stack, or its root. */
export function topOf(state: NavState, room: RoomId): NavEntry {
  const stack = state.stacks[room];
  return stack[stack.length - 1] ?? state.roots[room];
}

/** The same place: room, view and record. Labels and data do not make two entries different. */
export function sameEntry(a: NavEntry, b: NavEntry): boolean {
  return a.room === b.room && a.view === b.view && a.id === b.id;
}

/**
 * Switches to `room`. The first visit mounts it. Choosing the room that is already active
 * clears its stack, which is "go to the root".
 */
export function switchRoom(state: NavState, room: RoomId): NavState {
  const visited = state.visited.includes(room)
    ? state.visited
    : [...state.visited, room];
  if (room === state.active) {
    if (state.stacks[room].length === 0) return state;
    return { ...state, stacks: { ...state.stacks, [room]: [] } };
  }
  return { ...state, active: room, visited };
}

/**
 * Pushes `entry` on the active room's stack. The same place twice in a row is ignored. A place that
 * is already in the stack is not added again: the stack is cut back to it, so a loop such as Anna,
 * a task, Anna, a task never grows and one Back leads to the place before. `replace` swaps the top
 * layer for `entry` (a finalized draft becomes its entry). Beyond STACK_LIMIT the oldest is dropped.
 */
export function pushEntry(
  state: NavState,
  entry: NavEntry,
  options?: { replace?: boolean },
): NavState {
  const current = state.stacks[state.active];
  if (options?.replace && current.length > 0) {
    const stack = [...current.slice(0, -1), entry];
    return { ...state, stacks: { ...state.stacks, [state.active]: stack } };
  }
  if (sameEntry(topOf(state, state.active), entry)) return state;
  const earlier = current.findIndex((layer) => sameEntry(layer, entry));
  if (earlier !== -1) {
    return {
      ...state,
      stacks: {
        ...state.stacks,
        [state.active]: current.slice(0, earlier + 1),
      },
    };
  }
  const stack = [...current, entry].slice(-STACK_LIMIT);
  return {
    ...state,
    stacks: { ...state.stacks, [state.active]: stack },
  };
}

/** True when Back has something to remove in the active room. */
export function canGoBack(state: NavState): boolean {
  return state.stacks[state.active].length > 0;
}

/** Removes the top of the active room's stack; nothing happens when the stack is empty. */
export function goBack(state: NavState): NavState {
  if (!canGoBack(state)) return state;
  return {
    ...state,
    stacks: {
      ...state.stacks,
      [state.active]: state.stacks[state.active].slice(0, -1),
    },
  };
}

/**
 * The list views a record opens beside in a wide frame (desktop spec 2.1): Work's Agenda, Status and Projekt, the
 * Contact list, the Journal's day and Start's suggestions. Control, Shopping (which splits inside its own view) and the other overviews keep
 * one column.
 */
const SPLIT_LISTS: Readonly<Record<string, readonly string[]>> = {
  start: [ROOT_VIEW, "suggestions"],
  work: [ROOT_VIEW, "agenda", "board", "hierarchy"],
  contacts: [ROOT_VIEW, "list"],
  journal: [ROOT_VIEW, "day"],
};

/** How a list lays out: a column beside the detail, or a wide view (Status's columns) the detail lies over. */
export type ListLayout = "list" | "wide";

/**
 * How a room's pane is drawn, by layer index (0 is the root, n the stack's n-th entry, as layersOf counts them).
 *
 * - `single`: the top layer alone, as below 64rem (the phone, a narrow frame, Control, a wide view with nothing open).
 * - `aside`: a list on top in a wide frame with no record open: the list and, beside it, the room's aside or the hints.
 * - `split`: the nearest list under the top record on the left and the record on the right; the records between them
 *   stay mounted and hidden, and the detail's own head leads back to them.
 * - `drawer`: the record over a wide view (the Status board), as a drawer from the right; the view does not move.
 */
export type Split =
  | { kind: "single" }
  | { kind: "aside"; list: number }
  | { kind: "split" | "drawer"; list: number; detail: number };

/**
 * The shell's rule for when a pane is split (desktop spec 2.1), pure. `wide` is a frame of 64rem or more where the
 * shell drives the rooms. `layouts` is what a list layer said of itself, by layer index (Work's tabs: the Status tab is
 * a wide view whatever view opened the room); a list that said nothing is a wide view when it is the board and a
 * column otherwise.
 */
export function splitOf(
  state: NavState,
  room: RoomId,
  frame: {
    wide: boolean;
    layouts?: Readonly<Partial<Record<number, ListLayout>>>;
  },
): Split {
  if (!frame.wide) return { kind: "single" };
  const entries = [state.roots[room], ...state.stacks[room]];
  const detail = entries.length - 1;
  const layoutAt = (index: number): ListLayout | undefined => {
    const entry = entries[index];
    if (!entry || SPLIT_LISTS[entry.room]?.includes(entry.view) !== true)
      return undefined;
    return frame.layouts?.[index] ?? (entry.view === "board" ? "wide" : "list");
  };
  const top = entries[detail];
  if (!top) return { kind: "single" };
  if (!isRecordEntry(top))
    return layoutAt(detail) === "list"
      ? { kind: "aside", list: detail }
      : { kind: "single" };
  let list = detail - 1;
  while (list >= 0 && isRecordEntry(entries[list] ?? top)) list -= 1;
  const layout = list >= 0 ? layoutAt(list) : undefined;
  if (layout === undefined) return { kind: "single" };
  return { kind: layout === "wide" ? "drawer" : "split", list, detail };
}

/**
 * Opens `entry` beside the list at layer `list` of the active room: the stack is cut back to that list and `entry` put
 * on it, so stepping through a list (j/k, a click on the next row) swaps the detail and never builds a stack, and the
 * records the detail had opened above itself (a Contact from its Task) go with it. Opening the record already shown
 * there changes nothing.
 */
export function openBeside(
  state: NavState,
  list: number,
  entry: NavEntry,
): NavState {
  const current = state.stacks[state.active];
  const kept = current.slice(0, Math.max(0, list));
  const shown = current[kept.length];
  if (current.length === kept.length + 1 && shown && sameEntry(shown, entry))
    return state;
  return {
    ...state,
    stacks: { ...state.stacks, [state.active]: [...kept, entry] },
  };
}

/** Closes what is open beside the list at layer `list` of the active room: the stack is cut back to that list. */
export function closeBeside(state: NavState, list: number): NavState {
  const current = state.stacks[state.active];
  if (current.length <= list) return state;
  return {
    ...state,
    stacks: {
      ...state.stacks,
      [state.active]: current.slice(0, Math.max(0, list)),
    },
  };
}
