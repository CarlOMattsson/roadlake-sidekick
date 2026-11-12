/**
 * Navigation state of the Sidekick shell, as pure functions (no React), so the rules in the design
 * (docs/explanation/architecture/mcp-apps.md, "Entry, navigation and durable context") can be tested one by one.
 *
 * One stack per room. A cross-link pushes its target on the stack of the room the user is in, so the
 * strip keeps showing that room. Back pops the top. Pressing the active room returns to its root.
 * There is no window.history: the state lives in memory only.
 */
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";

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
 * reads "‹ Arbete".
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
