import type { WorkShellTab } from "./work-shell";

/**
 * The tab state of WorkShell as a reducer: the tab shown and the tabs pressed at least once. Only the
 * visited tabs are rendered, so an unvisited tab mounts nothing (and reads nothing) until it is pressed.
 */
export type WorkTabsState = {
  tab: WorkShellTab;
  visited: ReadonlySet<WorkShellTab>;
};

export type WorkTabsAction = { type: "choose"; tab: WorkShellTab };

export function createWorkTabsState(initialTab: WorkShellTab): WorkTabsState {
  return { tab: initialTab, visited: new Set([initialTab]) };
}

export function workTabsReducer(
  state: WorkTabsState,
  action: WorkTabsAction,
): WorkTabsState {
  const visited = state.visited.has(action.tab)
    ? state.visited
    : new Set([...state.visited, action.tab]);
  return state.tab === action.tab && visited === state.visited
    ? state
    : { tab: action.tab, visited };
}
