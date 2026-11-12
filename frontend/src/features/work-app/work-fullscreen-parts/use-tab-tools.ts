import { useMemo, useReducer, useRef } from "react";

import type { WorkTab } from "../work-shell";
import { initialToolsState, toolsReducer } from "./tools-reducer";

/**
 * The tab row's tools (search, +, "⋯", stack depth) over `toolsReducer`, with the two side effects the reducer cannot
 * have: closing search or the new-Task field gives the focus back to the button that opened it.
 */
export function useTabTools() {
  const [state, dispatch] = useReducer(toolsReducer, initialToolsState);
  const searchToggle = useRef<HTMLButtonElement>(null);
  const createToggle = useRef<HTMLButtonElement>(null);
  // Stable per tab: the views take them as effect dependencies.
  const setDepth = useMemo(() => {
    const at = (tab: WorkTab) => (depth: number) =>
      dispatch({ type: "depth", tab, depth });
    return {
      agenda: at("agenda"),
      board: at("board"),
      hierarchy: at("hierarchy"),
    };
  }, []);
  return {
    state,
    dispatch,
    searchToggle,
    createToggle,
    setDepth,
    /** Opens the tab's new-Task field, as + does (closing its search first); the empty Agenda and Status call it. */
    openCreate: (tab: WorkTab) => dispatch({ type: "openCreate", tab }),
    closeCreate: (tab: WorkTab) => {
      dispatch({ type: "closeCreate", tab });
      createToggle.current?.focus();
    },
    openSearch: (tab: WorkTab) => dispatch({ type: "openSearch", tab }),
    closeSearch: (tab: WorkTab) => {
      dispatch({ type: "closeSearch", tab });
      searchToggle.current?.focus();
    },
    setQuery: (tab: WorkTab, query: string) =>
      dispatch({ type: "query", tab, query }),
  };
}

export type TabTools = ReturnType<typeof useTabTools>;
