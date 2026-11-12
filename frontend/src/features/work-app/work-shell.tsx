import { useContext, useReducer, type ReactNode } from "react";

import { AppFrame } from "../mcp-apps/ui/layout";
import { RoomSurfaceContext } from "../mcp-apps/ui/room-context";
import { ViewTabs, type ViewTabOption } from "./view-tabs";
import type { WorkShellLabels } from "./work-shell-labels";
import { createWorkTabsState, workTabsReducer } from "./work-shell-tabs";
import "./work-shell.css";

export type WorkTab = "agenda" | "board" | "hierarchy";

const TAB_ORDER: readonly WorkTab[] = ["agenda", "board", "hierarchy"];

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
  onTabChange?: (tab: WorkTab) => void;
  /**
   * Optional detail for an open item. A wide frame shows it beside the list; a narrow frame shows it
   * alone with the back button. The shell does not change the detail when the tab changes.
   */
  detail?: ReactNode;
  /** Called by the back button in the detail column. Shown only when this and `detail` are set. */
  onBack?: () => void;
  /**
   * Optional control beside the tab strip, on the same row (e.g. the board's saved views toggle). The
   * caller hides it when it does not belong to the tab shown. An open panel wraps onto its own row.
   */
  tabsEnd?: ReactNode;
};

/**
 * Fullscreen shell for the Work app: a tab strip at the top (Agenda, Board, Hierarki)
 * above the active tab's content. The strip is at the top, not the bottom, because the composer
 * sits at the bottom of the host. Density follows the frame width (`.sk-wide`), not breakpoints.
 */
export function WorkShell({
  labels,
  initialTab = "agenda",
  agenda,
  board,
  hierarchy,
  tabs: offeredTabs = TAB_ORDER,
  onTabChange,
  detail,
  onBack,
  tabsEnd,
}: WorkShellProps) {
  const { heading } = useContext(RoomSurfaceContext);
  const [{ tab, visited }, dispatch] = useReducer(
    workTabsReducer,
    initialTab,
    createWorkTabsState,
  );

  function choose(next: WorkTab) {
    dispatch({ type: "choose", tab: next });
    onTabChange?.(next);
  }

  const tabs = TAB_ORDER.filter((value) => offeredTabs.includes(value));
  const options: ViewTabOption<WorkTab>[] = tabs.map((value) => ({
    value,
    label: labels.tabs[value],
  }));
  const panels: Record<WorkTab, ReactNode> = {
    agenda,
    board,
    hierarchy,
  };
  const hasDetail = detail !== undefined && detail !== null && detail !== false;

  return (
    <AppFrame mode="full">
      <div className="sk-shell" data-detail={hasDetail ? "open" : "closed"}>
        <div
          className={
            tabsEnd === undefined
              ? "sk-shell-tabs"
              : "sk-shell-tabs sk-shell-tabs--with-end"
          }
        >
          {tabs.length > 1 ? (
            <ViewTabs
              label={labels.tabsLabel}
              options={options}
              value={tab}
              onChange={choose}
            />
          ) : // One view: no tab strip, and the tools stay at the end of the row. With no room strip above (the phone's
          // single room) nothing else names the room, so its name stands here.
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
          )}
          {tabsEnd}
        </div>
        <div className="sk-wide">
          {tabs
            .filter((value) => visited.has(value))
            .map((value) => (
              <section
                key={value}
                className="sk-shell-list"
                aria-label={labels.tabs[value]}
                hidden={value !== tab}
              >
                {panels[value]}
              </section>
            ))}
          {hasDetail ? (
            <section aria-label={labels.detailLabel}>
              {onBack ? (
                <button
                  type="button"
                  className="sk-shell-back"
                  onClick={onBack}
                >
                  {labels.back}
                </button>
              ) : null}
              {detail}
            </section>
          ) : null}
        </div>
      </div>
    </AppFrame>
  );
}
