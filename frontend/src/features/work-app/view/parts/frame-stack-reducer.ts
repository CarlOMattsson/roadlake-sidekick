import type { WorkFrame } from "../../transport/transport";

/**
 * The navigation state of WorkView as one reducer: the frames, the session counter that remounts them
 * after a reset, the push/pop counter that moves focus, the stale flag and the Contact that opens in
 * its editor. Pure, so each transition is testable without React.
 */
export type FrameStackState = {
  /** The `initial` frame the stack was rooted on, so a new tool result re-roots it once. */
  seen: WorkFrame | undefined;
  stack: WorkFrame[];
  /** Bumped on every reset so a re-opened root always starts from fresh frames. */
  session: number;
  /** Bumped on every push or pop; a new frame moves focus to its heading only after a move. */
  moves: number;
  /** Set when a Task is saved: the board or agenda under it reads again when it is shown next. */
  stale: boolean;
  /** The Contact whose frame opens with its editor shown; cleared by every other push. */
  editContactId: string | undefined;
};

export type FrameStackAction =
  | { type: "reset"; initial: WorkFrame | undefined }
  | { type: "push"; frame: WorkFrame; edit?: boolean }
  | { type: "replace"; before: WorkFrame; after: WorkFrame }
  | { type: "back" }
  | { type: "stale"; stale: boolean };

export function createFrameStackState(
  initial: WorkFrame | undefined,
): FrameStackState {
  return {
    seen: initial,
    stack: initial ? [initial] : [],
    session: 0,
    moves: 0,
    stale: false,
    editContactId: undefined,
  };
}

/**
 * A board or agenda frame that re-read its page replaces itself, wherever it sits in the stack. Two patches
 * in one batch (two rows answering together) both start from the same `before`, and the first already
 * replaced it: the second then replaces the top frame when that is of the same kind, so neither is lost.
 */
function replaceFrame(
  stack: WorkFrame[],
  before: WorkFrame,
  after: WorkFrame,
): WorkFrame[] {
  if (stack.includes(before))
    return stack.map((frame) => (frame === before ? after : frame));
  const top = stack.at(-1);
  if (top && top.kind === after.kind) return [...stack.slice(0, -1), after];
  return stack;
}

export function frameStackReducer(
  state: FrameStackState,
  action: FrameStackAction,
): FrameStackState {
  switch (action.type) {
    case "reset":
      // A new initial (a new tool result) replaces the whole navigation stack.
      return {
        ...createFrameStackState(action.initial),
        session: state.session + 1,
      };
    case "push": {
      const { frame, edit } = action;
      return {
        ...state,
        stack: [...state.stack, frame],
        moves: state.moves + 1,
        editContactId: edit && frame.kind === "contact" ? frame.id : undefined,
      };
    }
    case "replace": {
      const stack = replaceFrame(state.stack, action.before, action.after);
      return stack === state.stack ? state : { ...state, stack };
    }
    case "back":
      return {
        ...state,
        stack: state.stack.length > 1 ? state.stack.slice(0, -1) : state.stack,
        moves: state.moves + 1,
      };
    case "stale":
      return state.stale === action.stale
        ? state
        : { ...state, stale: action.stale };
  }
}
