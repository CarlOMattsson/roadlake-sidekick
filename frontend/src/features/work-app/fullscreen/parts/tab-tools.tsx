import type { ReactNode } from "react";

import type { RoomHeadProps } from "../../../mcp-apps/ui/room-head";
import type { WorkTab } from "../../shell/work-shell";
import type { TabTools } from "./use-tab-tools";

/**
 * The tools of Work's room head (designsystem §3 "Rumshuvud"): search, + and "⋯", at the same places in all three
 * tabs (ui/room-head.tsx). Each tab has its own "⋯" (`menus`), mounted (hidden) on the others so an open menu keeps its
 * state. With a Task open over the list (`shown` false) the head keeps three empty boxes, so the tabs never move.
 * Search unfolds the field under the head and "/" opens it with the focus in the field; + unfolds the new-Task field
 * ("n").
 */
export function tabHeadTools({
  tools,
  activeTab,
  shown,
  createOff,
  createOffered,
  searchId,
  searchLabel,
  createLabel,
  menus,
}: {
  tools: TabTools;
  activeTab: WorkTab;
  shown: boolean;
  /** + and search are off until the tab's list has been read. */
  createOff: boolean;
  /** + needs create_task (the transport's own answer, WorkTransport.supportsTool). */
  createOffered: boolean;
  searchId: string;
  searchLabel: string;
  createLabel: string;
  menus: ReactNode;
}): Pick<RoomHeadProps, "search" | "add" | "more" | "searchRef" | "addRef"> {
  const searchOpen = Boolean(tools.state.searchOpen[activeTab]);
  const createOpen = Boolean(tools.state.createOpen[activeTab]);
  return {
    searchRef: tools.searchToggle,
    addRef: tools.createToggle,
    search: shown
      ? {
          label: searchLabel,
          expanded: searchOpen,
          controls: `${searchId}${activeTab}`,
          disabled: createOff,
          onPress: () =>
            searchOpen
              ? tools.closeSearch(activeTab)
              : tools.openSearch(activeTab),
          onKey: () => tools.openSearch(activeTab),
        }
      : undefined,
    add:
      shown && createOffered
        ? {
            label: createLabel,
            expanded: createOpen,
            controls: `${searchId}${activeTab}-new`,
            disabled: createOff,
            onPress: () =>
              createOpen
                ? tools.closeCreate(activeTab)
                : tools.openCreate(activeTab),
            onKey: () => tools.openCreate(activeTab),
          }
        : undefined,
    // The hidden menus of the other tabs draw nothing; with no menu shown the place keeps an empty box.
    more: shown ? (
      menus
    ) : (
      <>
        {menus}
        <span className="sk-room-head__slot" aria-hidden="true" />
      </>
    ),
  };
}
