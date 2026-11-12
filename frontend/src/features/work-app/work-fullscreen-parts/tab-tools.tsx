import type { ReactNode } from "react";

import { AgendaSearchToggle, CreateToggle } from "../agenda-toolbar";
import type { WorkTab } from "../work-shell";
import type { TabTools } from "./use-tab-tools";

/**
 * The tools at the end of the tab row (designsystem §3 "Rumshuvud"): search, +, then "⋯" outermost, at the same x in all
 * three tabs. Each tab has its own "⋯" (`menus`), mounted (hidden) on the others so an open menu keeps its state. With a
 * Task open over the list (`shown` false) the row keeps three empty 44 px boxes, so the tabs never move.
 */
export function TabToolsEnd({
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
}) {
  const slot = <span className="work-tab-slot" aria-hidden="true" />;
  return (
    <div className="sk-shell-tabs-end">
      {shown ? (
        <AgendaSearchToggle
          label={searchLabel}
          open={Boolean(tools.state.searchOpen[activeTab])}
          disabled={createOff}
          controls={`${searchId}${activeTab}`}
          buttonRef={tools.searchToggle}
          onOpenChange={(open) =>
            open ? tools.openSearch(activeTab) : tools.closeSearch(activeTab)
          }
        />
      ) : (
        slot
      )}
      {shown && createOffered ? (
        <CreateToggle
          label={createLabel}
          open={Boolean(tools.state.createOpen[activeTab])}
          disabled={createOff}
          controls={`${searchId}${activeTab}-new`}
          buttonRef={tools.createToggle}
          onOpenChange={(open) =>
            open ? tools.openCreate(activeTab) : tools.closeCreate(activeTab)
          }
        />
      ) : (
        slot
      )}
      {menus}
      {shown ? null : slot}
    </div>
  );
}
