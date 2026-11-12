import type { WorkTab } from "../work-shell";
import type { PerTab } from "./tab-data";

/**
 * Which tabs are out of date and which views read again, as one reducer. A tab is read again when it is shown and is out
 * of date, not at once while it is hidden: a write in the Agenda makes a mounted Board out of date, and the Board reads
 * when it is pressed. Pure, so each transition is testable.
 */
export type RefreshState = {
  /** Tabs marked out of date, waiting to be shown. */
  stale: PerTab<boolean>;
  /** Each tab's refreshKey: a new value reads the tab's list again in place. */
  bumps: PerTab<number>;
  /** The Agenda's Refresh (the view takes it as its own tick). */
  agendaTick: number;
  /** The Board's Refresh, added to the board's refreshKey. */
  boardTick: number;
};

export type RefreshAction =
  | { type: "stale"; tabs: readonly WorkTab[] }
  /** The shown tab's mark is cleared; `bump` says whether its view reads again. */
  | { type: "consume"; tab: WorkTab; bump: boolean }
  /** "Uppdatera" in a tab's "⋯": the Agenda and Board by their own tick, the Projects tab by its key. */
  | { type: "refresh"; tab: WorkTab };

export const initialRefreshState: RefreshState = {
  stale: {},
  bumps: {},
  agendaTick: 0,
  boardTick: 0,
};

export function refreshReducer(
  state: RefreshState,
  action: RefreshAction,
): RefreshState {
  switch (action.type) {
    case "stale": {
      if (action.tabs.length === 0) return state;
      const stale = { ...state.stale };
      for (const tab of action.tabs) stale[tab] = true;
      return { ...state, stale };
    }
    case "consume":
      return {
        ...state,
        stale: { ...state.stale, [action.tab]: false },
        bumps: action.bump
          ? { ...state.bumps, [action.tab]: (state.bumps[action.tab] ?? 0) + 1 }
          : state.bumps,
      };
    case "refresh":
      if (action.tab === "agenda")
        return { ...state, agendaTick: state.agendaTick + 1 };
      if (action.tab === "board")
        return { ...state, boardTick: state.boardTick + 1 };
      return {
        ...state,
        bumps: { ...state.bumps, hierarchy: (state.bumps.hierarchy ?? 0) + 1 },
      };
  }
}
