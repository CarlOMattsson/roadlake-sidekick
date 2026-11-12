import type { WorkTab } from "../../shell/work-shell";
import type { PerTab } from "./tab-data";

/**
 * The tab row's tools as one reducer. They live above the views, not in them: a saved view remounts its view, and the
 * search text, the open "⋯" menu and the stack depth must survive that. Pure, so each transition is testable.
 */
export type ToolsState = {
  /** Each tab's search text. */
  queries: PerTab<string>;
  /** Search folds away behind the search icon, in every tab; closing it clears the tab's text. */
  searchOpen: PerTab<boolean>;
  /** The new-Task field under the tab row. One field at a time: opening it closes search, and the other way round. */
  createOpen: PerTab<boolean>;
  /** The tab whose "⋯" menu is open. */
  moreOpen: WorkTab | undefined;
  /** Bumped when the search icon is pressed; the field takes the focus on a new value only. */
  searchFocus: number;
  /** Each opened saved view bumps its tab's key, so the view starts again on the new frame. */
  viewKeys: PerTab<number>;
  /** Tabs whose opened saved view names several priorities (such a view shows every priority). */
  severalPriorities: PerTab<boolean>;
  /** How deep each list's navigation stack is; deeper than 1, a Task or Project is open over the list. */
  depth: PerTab<number>;
};

export type ToolsAction =
  | { type: "openCreate"; tab: WorkTab }
  | { type: "closeCreate"; tab: WorkTab }
  | { type: "openSearch"; tab: WorkTab }
  | { type: "closeSearch"; tab: WorkTab }
  | { type: "query"; tab: WorkTab; query: string }
  | { type: "more"; tab: WorkTab; open: boolean }
  | { type: "viewApplied"; tab: WorkTab; several: boolean }
  | { type: "depth"; tab: WorkTab; depth: number };

export const initialToolsState: ToolsState = {
  queries: {},
  searchOpen: {},
  createOpen: {},
  moreOpen: undefined,
  searchFocus: 0,
  viewKeys: {},
  severalPriorities: {},
  depth: {},
};

/** Whether a Task or Project is open over the tab's list. */
export function isOpenOver(state: ToolsState, tab: WorkTab): boolean {
  return (state.depth[tab] ?? 1) > 1;
}

export function toolsReducer(
  state: ToolsState,
  action: ToolsAction,
): ToolsState {
  const { tab } = action;
  switch (action.type) {
    case "openCreate":
      return {
        ...state,
        searchOpen: { ...state.searchOpen, [tab]: false },
        queries: { ...state.queries, [tab]: "" },
        createOpen: { ...state.createOpen, [tab]: true },
      };
    case "closeCreate":
      return { ...state, createOpen: { ...state.createOpen, [tab]: false } };
    case "openSearch":
      return {
        ...state,
        createOpen: { ...state.createOpen, [tab]: false },
        searchOpen: { ...state.searchOpen, [tab]: true },
        searchFocus: state.searchFocus + 1,
      };
    case "closeSearch":
      return {
        ...state,
        searchOpen: { ...state.searchOpen, [tab]: false },
        queries: { ...state.queries, [tab]: "" },
      };
    case "query":
      return {
        ...state,
        queries: { ...state.queries, [tab]: action.query },
      };
    case "more":
      return { ...state, moreOpen: action.open ? tab : undefined };
    case "viewApplied":
      return {
        ...state,
        // The agenda's text is cleared with the view; the board keeps its own.
        queries:
          tab === "agenda" ? { ...state.queries, agenda: "" } : state.queries,
        viewKeys: { ...state.viewKeys, [tab]: (state.viewKeys[tab] ?? 0) + 1 },
        severalPriorities: {
          ...state.severalPriorities,
          [tab]: action.several,
        },
      };
    case "depth":
      return state.depth[tab] === action.depth
        ? state
        : { ...state, depth: { ...state.depth, [tab]: action.depth } };
  }
}
