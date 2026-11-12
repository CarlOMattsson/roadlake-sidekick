/**
 * The navigation state the Sidekick shell keeps in one reducer: the stacks of nav-state, what the shell
 * has already answered from its props (the card it was rooted on, the record it was told to open, whether
 * it was full), and the inline card's reread bookkeeping. Pure, so every transition is testable without React.
 */
import {
  createNavState,
  goBack,
  pushEntry,
  switchRoom,
  type NavEntry,
  type NavState,
} from "@/features/mcp-apps/nav-state";
import type { RoomId } from "@/features/mcp-apps/router";

export type ShellNavState = {
  nav: NavState;
  /** The `openAt` already pushed, so a change of it (and only a change) pushes again. */
  pushedOpenAt: NavEntry | undefined;
  /** The `full` already answered, so a switch between the card and the full view is seen once. */
  wasFull: boolean;
  /** The `start` the stacks were rooted on, so a new tool result re-roots them once. */
  seenStart: NavEntry;
  /** The inline card is mounted again with this key when a write in the full view touched its record. */
  inlineKey: number;
  /** Set by a write in the full view that touched the card's own domain. */
  inlineStale: boolean;
};

export type ShellNavProps = {
  start: NavEntry;
  openAt?: NavEntry;
  full: boolean;
};

export type ShellNavAction =
  /** What the props say now (see answerProps). */
  | ({ type: "props" } & ShellNavProps)
  | { type: "switch-room"; room: RoomId }
  | { type: "push"; target: NavEntry; replace?: boolean }
  | { type: "back" }
  /** A write in the full view that touched the card's own domain. */
  | { type: "inline-stale" };

export function createShellNavState(
  start: NavEntry,
  full: boolean,
): ShellNavState {
  return {
    nav: createNavState(start),
    pushedOpenAt: undefined,
    wasFull: full,
    seenStart: start,
    inlineKey: 0,
    inlineStale: false,
  };
}

/**
 * Moves the state toward the props; returns the same object when there is nothing to answer. The shell
 * dispatches "props" during render only when this differs, because a render-phase dispatch always renders again.
 */
export function answerProps(
  state: ShellNavState,
  { start, openAt, full }: ShellNavProps,
): ShellNavState {
  let next = state;
  if (full !== state.wasFull) {
    next = { ...next, wasFull: full };
    if (!full && next.inlineStale) {
      // Back in the card: it shows what the full view changed, not what the tool result said.
      next = { ...next, inlineStale: false, inlineKey: next.inlineKey + 1 };
    }
    if (full) {
      // The full view starts where the card pointed (a product decision), never in the room
      // visited last: the stack and the active room start again from the card's own entry.
      const fresh = createNavState(start);
      next = {
        ...next,
        nav: openAt ? pushEntry(fresh, openAt) : fresh,
        pushedOpenAt: openAt,
      };
    }
  } else if (openAt !== state.pushedOpenAt) {
    next = {
      ...next,
      pushedOpenAt: openAt,
      nav: openAt ? pushEntry(next.nav, openAt) : next.nav,
    };
  }
  // A new tool result re-roots the app in place: the rooms that keep their key get it as a new result.
  if (start !== next.seenStart) {
    next = { ...next, seenStart: start, nav: createNavState(start) };
  }
  return next;
}

export function shellNavReducer(
  state: ShellNavState,
  action: ShellNavAction,
): ShellNavState {
  switch (action.type) {
    case "props":
      return answerProps(state, action);
    case "switch-room": {
      const nav = switchRoom(state.nav, action.room);
      return nav === state.nav ? state : { ...state, nav };
    }
    case "push": {
      const nav = pushEntry(state.nav, action.target, {
        replace: action.replace,
      });
      return nav === state.nav ? state : { ...state, nav };
    }
    case "back": {
      const nav = goBack(state.nav);
      return nav === state.nav ? state : { ...state, nav };
    }
    case "inline-stale":
      return state.inlineStale ? state : { ...state, inlineStale: true };
  }
}
