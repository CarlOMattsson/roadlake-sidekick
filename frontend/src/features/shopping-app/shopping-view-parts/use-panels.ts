import { useReducer } from "react";

/**
 * The open or closed state of the view's folded parts. Choosing another list closes all of them at once.
 *
 * - `editOpen`: fullscreen "Edit list" (the rename form) instead of the store view.
 * - `moreOpen`: the ⋯ menu in the header of the fullscreen view.
 * - `expanded`: compact view, "Show all" expands the view in place.
 * - `boughtOpen`: the purchased items, folded until opened.
 * - `newOpen`: the "New list" form of the picker.
 * - `listsExpanded`: the picker shows every list row in an inline card.
 * - `archivedOpen`: the picker's folded group of archived lists.
 * - `addOpen`: the create field behind "+ Add item". It never opens by itself: focus would raise the keyboard.
 */
export type Panels = {
  editOpen: boolean;
  moreOpen: boolean;
  expanded: boolean;
  boughtOpen: boolean;
  newOpen: boolean;
  listsExpanded: boolean;
  archivedOpen: boolean;
  addOpen: boolean;
};

type PanelAction =
  | { type: "set"; key: keyof Panels; value: boolean }
  | { type: "closeAll" };

const CLOSED: Panels = {
  editOpen: false,
  moreOpen: false,
  expanded: false,
  boughtOpen: false,
  newOpen: false,
  listsExpanded: false,
  archivedOpen: false,
  addOpen: false,
};

function reducePanels(state: Panels, action: PanelAction): Panels {
  if (action.type === "closeAll")
    return Object.values(state).some(Boolean) ? CLOSED : state;
  return state[action.key] === action.value
    ? state
    : { ...state, [action.key]: action.value };
}

export function usePanels() {
  const [panels, dispatch] = useReducer(reducePanels, CLOSED);
  return {
    panels,
    setPanel: (key: keyof Panels, value: boolean) =>
      dispatch({ type: "set", key, value }),
    closeAll: () => dispatch({ type: "closeAll" }),
  };
}
