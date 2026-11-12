import type { WorkSavedView } from "../transport/transport";
import { upsertView, type ViewNameProblem } from "./saved-views";

export type ListPhase = "loading" | "ready" | "error";
/** The row being renamed: its id, the text typed so far, and why the text was refused. */
export type EditState = {
  id: string;
  value: string;
  problem?: ViewNameProblem;
};
/** The last archived view, kept for its Undo line, with the version the archive answered. */
export type UndoState = { id: string; name: string; version: number };

export type SavedViewsState = {
  /** The views of this tab; undefined until the first list answer. */
  views: WorkSavedView[] | undefined;
  listPhase: ListPhase;
  showArchived: boolean;
  /** The save form's name field and why it was refused. */
  name: string;
  nameProblem: ViewNameProblem | undefined;
  editing: EditState | undefined;
  undo: UndoState | undefined;
  /** The status line after a save, rename, archive or restore. */
  notice: string;
};

export type SavedViewsAction =
  | { type: "listLoading" }
  | { type: "listLoaded"; views: WorkSavedView[] }
  | { type: "listFailed" }
  | { type: "showArchivedSet"; value: boolean }
  | { type: "nameChanged"; value: string }
  | { type: "nameRefused"; problem: ViewNameProblem }
  | { type: "saved"; view: WorkSavedView; notice: string }
  | { type: "renameStarted"; view: WorkSavedView }
  | { type: "renameTyped"; id: string; value: string }
  | {
      type: "renameRefused";
      id: string;
      value: string;
      problem: ViewNameProblem;
    }
  | { type: "renameCancelled" }
  | { type: "renamed"; view: WorkSavedView; notice: string }
  | { type: "archived"; view: WorkSavedView }
  | { type: "restored"; view: WorkSavedView; notice: string };

export const initialSavedViewsState: SavedViewsState = {
  views: undefined,
  listPhase: "loading",
  showArchived: false,
  name: "",
  nameProblem: undefined,
  editing: undefined,
  undo: undefined,
  notice: "",
};

export function savedViewsReducer(
  state: SavedViewsState,
  action: SavedViewsAction,
): SavedViewsState {
  switch (action.type) {
    case "listLoading":
      return { ...state, listPhase: "loading" };
    case "listLoaded":
      return { ...state, views: action.views, listPhase: "ready" };
    case "listFailed":
      return { ...state, listPhase: "error" };
    case "showArchivedSet":
      return { ...state, showArchived: action.value };
    case "nameChanged":
      return { ...state, name: action.value, nameProblem: undefined };
    case "nameRefused":
      return { ...state, nameProblem: action.problem };
    case "saved":
      return {
        ...state,
        views: upsertView(state.views ?? [], action.view),
        notice: action.notice,
        name: "",
        nameProblem: undefined,
      };
    case "renameStarted":
      return {
        ...state,
        editing: { id: action.view.id, value: action.view.name },
      };
    case "renameTyped":
      return { ...state, editing: { id: action.id, value: action.value } };
    case "renameRefused":
      return {
        ...state,
        editing: {
          id: action.id,
          value: action.value,
          problem: action.problem,
        },
      };
    case "renameCancelled":
      return { ...state, editing: undefined };
    case "renamed":
      return {
        ...state,
        views: upsertView(state.views ?? [], action.view),
        editing: undefined,
        notice: action.notice,
      };
    case "archived":
      return {
        ...state,
        views: upsertView(state.views ?? [], action.view),
        editing:
          state.editing?.id === action.view.id ? undefined : state.editing,
        undo: {
          id: action.view.id,
          name: action.view.name,
          version: action.view.version,
        },
        notice: "",
      };
    case "restored":
      return {
        ...state,
        views: upsertView(state.views ?? [], action.view),
        undo: state.undo?.id === action.view.id ? undefined : state.undo,
        notice: action.notice,
      };
  }
}
