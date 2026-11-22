import { useContext, useEffect, useReducer, type ReactNode } from "react";

import { AppFrame } from "../../mcp-apps/ui/layout";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import { RoomHead, type RoomHeadProps } from "../../mcp-apps/ui/room-head";
import { useListLayout } from "../../mcp-apps/ui/split-layout";
import { ViewTabs, type ViewTabOption } from "./view-tabs";
import type { WorkShellLabels } from "./work-shell-labels";
import { createWorkTabsState, workTabsReducer } from "./work-shell-tabs";
import "./work-shell.css";

export type WorkTab = "agenda" | "board" | "hierarchy";
/** The shell's tabs: the three views, and To sort (Att sortera) while the shell offers it (`unsorted`). */
export type WorkShellTab = WorkTab | "unsorted";

const TAB_ORDER: readonly WorkTab[] = ["agenda", "board", "hierarchy"];

/** The letter of each tab after `g` (desktop spec 2.6): Agenda, Status, Projekt, Att sortera. */
const TAB_KEYS: Record<WorkShellTab, string> = {
  agenda: "a",
  board: "s",
  hierarchy: "p",
  unsorted: "t",
};

/** The To sort tab (desktop spec 3.1): its label, the count after it, and its content. */
export type WorkShellUnsorted = {
  label: string;
  /** How many wait; absent while the count is not known or is 0. */
  count?: number;
  content: ReactNode;
};

export type WorkShellProps = {
  /** Labels for the host locale, e.g. workShellLabelsFor(locale). */
  labels: WorkShellLabels;
  /**
   * The tab shown first. It is read once on mount, so the caller sets it from the tool result and
   * changes `key` when a new result arrives. Switching tabs is local and never calls the model.
   */
  initialTab?: WorkTab;
  /**
   * Content of each tab. Only the pressed tab is shown. A tab is rendered only once it has been
   * pressed, and then stays mounted (hidden) so its state survives switching tabs.
   */
  agenda: ReactNode;
  board: ReactNode;
  hierarchy: ReactNode;
  /**
   * The tabs to offer, in the shell's order. Absent: all three. With one tab there is no tab strip.
   * `initialTab` must be one of them.
   */
  tabs?: readonly WorkTab[];
  /** Called with the new tab each time a tab is pressed, so the host knows which tab is visible. */
  onTabChange?: (tab: WorkShellTab) => void;
  /**
   * To sort as the last tab, with its count (desktop spec 3.1, a wide frame with Tasks to sort). Absent: no such tab,
   * and a shown To sort tab gives way to the first tab.
   */
  unsorted?: WorkShellUnsorted;
  /**
   * The tools at the end of the room head (search, + and the tab's ⋯), at fixed places in every tab; an absent tool
   * keeps its empty box.
   */
  tools?: Pick<
    RoomHeadProps,
    "search" | "add" | "more" | "searchRef" | "addRef"
  >;
};

/**
 * Fullscreen shell for the Work app: the room head (ui/room-head.tsx: Agenda, Status, Projekt and the tools) at the top
 * above the active tab's content; in a wide frame the head stands in the shell's own row. The strip is at the top, not the bottom, because the composer
 * sits at the bottom of the host. Density follows the frame width, not breakpoints.
 */
export function WorkShell({
  labels,
  initialTab = "agenda",
  agenda,
  board,
  hierarchy,
  tabs: offeredTabs = TAB_ORDER,
  onTabChange,
  unsorted,
  tools,
}: WorkShellProps) {
  const { heading } = useContext(RoomSurfaceContext);
  const [{ tab, visited }, dispatch] = useReducer(
    workTabsReducer,
    initialTab,
    createWorkTabsState,
  );

  // In a wide frame a record opens beside Agenda and Projekt, and over the wide views (Status's columns, To sort's
  // one-line rows) as a drawer.
  useListLayout(tab === "board" || tab === "unsorted" ? "wide" : "list");

  function choose(next: WorkShellTab) {
    dispatch({ type: "choose", tab: next });
    onTabChange?.(next);
  }

  const views = TAB_ORDER.filter((value) => offeredTabs.includes(value));
  const tabs: WorkShellTab[] = unsorted ? [...views, "unsorted"] : views;
  const first = views[0] ?? "agenda";
  // To sort is gone (the frame narrowed) while it is shown: the first tab takes its place.
  const lost = tab === "unsorted" && !unsorted;
  useEffect(() => {
    if (!lost) return;
    dispatch({ type: "choose", tab: first });
    onTabChange?.(first);
  }, [lost, first, onTabChange]);
  const tabLabel = (value: WorkShellTab) =>
    value === "unsorted" ? (unsorted?.label ?? "") : labels.tabs[value];
  const options: ViewTabOption<WorkShellTab>[] = tabs.map((value) => ({
    value,
    label: tabLabel(value),
    count: value === "unsorted" ? unsorted?.count : undefined,
  }));
  const panels: Record<WorkShellTab, ReactNode> = {
    agenda,
    board,
    hierarchy,
    unsorted: unsorted?.content,
  };

  return (
    <AppFrame mode="full">
      <div className="sk-shell">
        <RoomHead
          scope="sidekick-work"
          className="sk-shell-tabs"
          keysTitle={labels.room}
          views={
            tabs.length > 1
              ? tabs.map((value) => ({
                  key: TAB_KEYS[value],
                  label: tabLabel(value),
                  onChoose: () => choose(value),
                }))
              : []
          }
          {...tools}
          tabs={
            tabs.length > 1 ? (
              <ViewTabs
                label={labels.tabsLabel}
                options={options}
                value={tab}
                onChange={choose}
              />
            ) : // One view: no tab strip, and the tools stay at the end of the row. With no room strip above (the
            // phone's single room) nothing else names the room, so its name stands here.
            heading ? (
              <p
                className="sk-shell-tabs-fill sk-shell-tabs-title"
                role="heading"
                aria-level={2}
              >
                {heading}
              </p>
            ) : (
              <span className="sk-shell-tabs-fill" aria-hidden="true" />
            )
          }
        />
        {tabs
          .filter((value) => visited.has(value))
          .map((value) => (
            <section
              key={value}
              className="sk-shell-list"
              aria-label={tabLabel(value)}
              hidden={value !== tab}
            >
              {panels[value]}
            </section>
          ))}
      </div>
    </AppFrame>
  );
}
