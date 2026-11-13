import type { WorkStep } from "../transport/transport";
import { appendSteps } from "./step-pages";

export type StepsPhase = "loading" | "ready" | "forbidden" | "error";
export type StepNotice =
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "invalid" }
  | { kind: "notFound" }
  | { kind: "failed"; stepId: string };

/** A Step archived during this visit, with the version its archive returned (what Restore needs). */
export type ArchivedStep = {
  id: string;
  title: string;
  version: number;
  /** The place the Step had when it was archived; a restore falls back to the row now there. */
  index: number;
};

/**
 * The Step checked or unchecked last: `done` is the state the check gave it, so Undo writes the other
 * state against the version the check left (`version`).
 */
export type StepUndo = {
  id: string;
  title: string;
  version: number;
  done: boolean;
};

export type StepsState = {
  phase: StepsPhase;
  steps: WorkStep[];
  /** Bumped to read the list again; the read effect depends on it. */
  attempt: number;
  /** The Step whose check is being written. */
  busyId: string | undefined;
  /** True while a re-read of the list is in flight; checkboxes wait for the fresh list. */
  refreshing: boolean;
  /**
   * Where the next page of Steps starts while the Task has more than the view has read; Show more
   * continues from it. A reorder needs every active Step, so the Up and Down controls wait for it.
   */
  nextCursor: string | undefined;
  more: "idle" | "busy" | "failed";
  notice: StepNotice | undefined;
  archived: ArchivedStep[];
  /** The Step archived last, whose Undo line is shown; Undo, Restore or a newer archive replaces it. */
  undo: ArchivedStep | undefined;
  /** The Step checked last, whose row shows Ångra until it runs out, another write, or Undo. */
  stepUndo: StepUndo | undefined;
  /** The status line after a move, a restore or an added Step. */
  status: string | undefined;
};

export type StepsAction =
  | {
      type: "loaded";
      items: WorkStep[];
      cursor: string | undefined;
      failed: boolean;
    }
  | { type: "loadFailed"; forbidden: boolean }
  | { type: "retryLoad" }
  | { type: "reload" }
  /** Every write clears the status line, the notice and the Undo line of the write before it. */
  | { type: "writeStarted" }
  | { type: "checkStarted"; id: string }
  | { type: "checkSettled" }
  | { type: "checked"; step: WorkStep }
  | { type: "stepUndoSet"; stepUndo: StepUndo | undefined }
  | { type: "noticed"; notice: StepNotice }
  /** The Step is gone: the list is read again so its row leaves, and the notice says why. */
  | { type: "notFound" }
  | { type: "reordered"; items: WorkStep[]; status: string }
  | { type: "moreStarted" }
  | { type: "moreLoaded"; items: WorkStep[]; cursor: string | undefined }
  | { type: "moreFailed" }
  | { type: "archived"; item: ArchivedStep }
  | { type: "restored"; item: ArchivedStep; status: string }
  | { type: "created"; step: WorkStep; status: string }
  /** The Step's Actions were read or changed: its row now knows how many active ones it has. */
  | { type: "actionsCounted"; stepId: string; count: number };

/**
 * `step` with the Action count the view already held for it. The Step writes answer without a count,
 * so the count read with the list is carried over rather than lost.
 */
function keepActionCount(
  step: WorkStep,
  known: WorkStep | undefined,
): WorkStep {
  const count = step.action_count ?? known?.action_count;
  return count === undefined ? step : { ...step, action_count: count };
}

export const initialStepsState: StepsState = {
  phase: "loading",
  steps: [],
  attempt: 0,
  busyId: undefined,
  refreshing: false,
  nextCursor: undefined,
  more: "idle",
  notice: undefined,
  archived: [],
  undo: undefined,
  stepUndo: undefined,
  status: undefined,
};

export function stepsReducer(
  state: StepsState,
  action: StepsAction,
): StepsState {
  switch (action.type) {
    case "loaded":
      return {
        ...state,
        steps: action.items,
        nextCursor: action.cursor,
        more: action.failed ? "failed" : "idle",
        refreshing: false,
        phase: "ready",
      };
    case "loadFailed":
      return {
        ...state,
        refreshing: false,
        phase: action.forbidden ? "forbidden" : "error",
      };
    case "retryLoad":
      return { ...state, phase: "loading", attempt: state.attempt + 1 };
    case "reload":
      return {
        ...state,
        notice: undefined,
        refreshing: true,
        attempt: state.attempt + 1,
      };
    case "writeStarted":
      return {
        ...state,
        status: undefined,
        notice: undefined,
        stepUndo: undefined,
      };
    case "checkStarted":
      return {
        ...state,
        busyId: action.id,
        status: undefined,
        notice: undefined,
        stepUndo: undefined,
      };
    case "checkSettled":
      return { ...state, busyId: undefined };
    case "checked":
      return {
        ...state,
        refreshing: false,
        steps: state.steps.map((item) =>
          item.id === action.step.id
            ? keepActionCount(action.step, item)
            : item,
        ),
      };
    case "stepUndoSet":
      return { ...state, stepUndo: action.stepUndo };
    case "noticed":
      return { ...state, notice: action.notice };
    case "notFound":
      return {
        ...state,
        notice: { kind: "notFound" },
        refreshing: true,
        attempt: state.attempt + 1,
      };
    case "reordered":
      return {
        ...state,
        refreshing: false,
        steps: action.items.map((item) =>
          keepActionCount(
            item,
            state.steps.find((known) => known.id === item.id),
          ),
        ),
        nextCursor: undefined,
        status: action.status,
      };
    case "moreStarted":
      return { ...state, more: "busy" };
    case "moreLoaded":
      return {
        ...state,
        steps: appendSteps(state.steps, action.items),
        nextCursor: action.cursor,
        more: "idle",
      };
    case "moreFailed":
      return { ...state, more: "failed" };
    case "archived":
      return {
        ...state,
        refreshing: false,
        steps: state.steps.filter((step) => step.id !== action.item.id),
        archived: [...state.archived, action.item],
        undo: action.item,
      };
    case "restored":
      return {
        ...state,
        archived: state.archived.filter((entry) => entry.id !== action.item.id),
        undo: state.undo?.id === action.item.id ? undefined : state.undo,
        status: action.status,
        refreshing: true,
        attempt: state.attempt + 1,
      };
    case "created":
      return {
        ...state,
        refreshing: false,
        steps: [
          ...state.steps.filter((item) => item.id !== action.step.id),
          // A new Step has no Actions yet.
          { action_count: 0, ...action.step },
        ],
        status: action.status,
      };
    case "actionsCounted":
      return {
        ...state,
        steps: state.steps.map((item) =>
          item.id === action.stepId
            ? { ...item, action_count: action.count }
            : item,
        ),
      };
  }
}
