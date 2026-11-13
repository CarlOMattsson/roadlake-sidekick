import { useCallback, useId, useState, type ReactNode } from "react";

import { Notice } from "../../mcp-apps/ui/notice";
import { AgendaSearch } from "../agenda/agenda-toolbar";
import type { CardLabels } from "../shared/card-labels";
import type { InlineSummaryLabels } from "../inline/inline-summary-labels";
import { BoardClearSearch, BoardQuery } from "../board/board";
import { workStatusLabel, type WorkLabels } from "../shared/labels";
import { manageLabelsFor } from "../shared/manage-labels";
import { NewTaskInput, RecentTasks } from "../tasks/new-task-input";
import { WorkNewTaskContext } from "../shared/empty-actions";
import { newTaskInputLabelsFor } from "../tasks/new-task-input-labels";
import type { SavedViewTab } from "../saved-views/saved-views";
import { SavedViewReceipt } from "../saved-views/saved-view-receipt";
import { SavedViewsBar } from "../saved-views/saved-views-bar";
import { savedViewsLabelsFor } from "../saved-views/saved-views-labels";
import type {
  WorkFilters,
  WorkFrame,
  WorkTask,
  WorkTransport,
} from "../transport/transport";
import type { WorkShellLabels } from "../shell/work-shell-labels";
import { WorkShell, type WorkTab } from "../shell/work-shell";
import { UnsortedOpenRow } from "../unsorted/unsorted-view";
import { WorkView } from "../view/work-view";
import { isOpenOver } from "./parts/tools-reducer";
import { SortingPage } from "../unsorted/sorting-page";
import { TabMore } from "./parts/tab-more";
import { TabPanel } from "./parts/tab-panel";
import { TabToolsEnd } from "./parts/tab-tools";
import {
  filtersOf,
  isTabFrame,
  TABS,
  type PerTab,
  type WorkTabFrame,
} from "./parts/tab-data";
import { useTabFreshness } from "./parts/use-tab-freshness";
import { useTabReads } from "./parts/use-tab-reads";
import { useTabTools } from "./parts/use-tab-tools";
import { useUnsorted } from "../unsorted/use-unsorted";
import type { HostSettingsEntry, RoomTarget } from "../../mcp-apps/room-types";
import { useToolSupport } from "../../mcp-apps/tool-support";

/** The filters as one comparable text, whatever order their keys were added in. */
function filterKey(filters: WorkFilters): string {
  return JSON.stringify(
    Object.entries(filters).sort(([a], [b]) => a.localeCompare(b)),
  );
}

export type WorkFullscreenProps = {
  transport: WorkTransport;
  /**
   * The frame the tool result gave. Its kind picks the first tab and is shown at once; any other
   * kind starts on Agenda, which is read on mount. Read once, so the caller changes `key` per result.
   */
  initial?: WorkFrame;
  /** The tab to start on when `initial` is absent or is not a tab frame (a room mounted hidden). Agenda when absent. */
  startTab?: WorkTab;
  /**
   * The tabs the host can serve. Absent: all three. A tab not listed has no tab, no "⋯" menu and is never read; a first
   * frame or start tab of another kind falls back to the first listed tab. One tab: no tab strip.
   */
  tabs?: readonly WorkTab[];
  labels: WorkLabels;
  shellLabels: WorkShellLabels;
  cardLabels?: CardLabels;
  inlineLabels?: InlineSummaryLabels;
  /** Host locale for the error notice; "en" when absent. */
  locale?: string;
  /** Opens a Journal entry linked to a Contact, shown in the Contact frames of the tabs. Absent: no Journal section. */
  onOpenJournalEntry?: (entry: { id: string; title: string }) => void;
  /** Given by a host that routes: Tasks, Projects, Contacts and the To sort page are steps on its stack. */
  onRoute?: (target: RoomTarget) => void;
  /**
   * Whether the host can answer a tool at all (RoomTransport.supportsTool). Absent: every tool. A menu item whose tool
   * the host lacks is not offered: Sparade vyer (with its archived views) needs list_saved_work_views, Control list_trash.
   */
  supportsTool?: (name: string) => boolean;
  /** The host's own settings: the ⋯ menu's last entry in Control's place (the phone's "Inställningar"). */
  hostSettings?: HostSettingsEntry;
  /** A new value reads the shown lists again in place (tab, filters, scroll and typed text stay). */
  refreshKey?: number;
  /**
   * False while the room is hidden or another layer covers it. A hidden room reads nothing (its first tab, the To
   * sort count); it reads what it needs when it is shown.
   */
  active?: boolean;
};

/**
 * Fullscreen Work app: the tab shell with Agenda, Board and Hierarchy. Contacts is a room of its own. The tab of the
 * first frame shows it at once; every other tab is read the first time it is opened and kept, so
 * switching tabs is local and never calls the model. A visited tab stays mounted (hidden) with its
 * state, and only the visible tab has keyboard shortcuts. The To sort view (Att sortera) opens from a
 * quiet row after the agenda, not from a tab: it covers the shell, which stays mounted, and Back returns.
 */
export function WorkFullscreen({
  transport,
  initial,
  startTab = "agenda",
  tabs: offeredTabs,
  labels,
  shellLabels,
  cardLabels,
  inlineLabels,
  locale = "en",
  onOpenJournalEntry,
  onRoute,
  supportsTool,
  hostSettings,
  refreshKey,
  active = true,
}: WorkFullscreenProps) {
  const offers = useToolSupport(transport);
  const offered = offeredTabs ?? TABS;
  // A first frame of a tab the host cannot serve is not shown; the room starts on the first listed tab.
  const firstFrame =
    initial && isTabFrame(initial) && offered.includes(initial.kind)
      ? initial
      : undefined;
  const initialTab: WorkTab = firstFrame
    ? firstFrame.kind
    : offered.includes(startTab)
      ? startTab
      : (offered[0] ?? "agenda");
  // The pressed tab, as the shell reports it. Only that tab's panel gets keyboard shortcuts.
  const [activeTab, setActiveTab] = useState<WorkTab>(initialTab);
  // The tab row's tools live here, not in the views: a saved view remounts its view, and the search text, the open
  // "⋯" menu and the saved views bar (status, focus) must survive that.
  const tools = useTabTools();
  const { dispatch: dispatchTools, state: ui } = tools;
  const onViewApplied = useCallback(
    (tab: SavedViewTab, several: boolean, name: string) =>
      dispatchTools({ type: "viewApplied", tab, several, name }),
    [dispatchTools],
  );
  const onViewCleared = useCallback(
    (tab: SavedViewTab) => dispatchTools({ type: "viewCleared", tab }),
    [dispatchTools],
  );
  const reads = useTabReads({
    transport,
    offers,
    initialTab,
    firstFrame,
    onViewApplied,
    onViewCleared,
  });
  const { entries, retry, applyView, clearView } = reads;
  // The filters each list shows now (a tag chosen in it), which a saved view is made from; a list not yet told
  // falls back to the filters it was read with.
  const [listFilters, setListFilters] = useState<PerTab<WorkFilters>>({});
  // Tasks added with the new-Task row, newest first. The agenda lists dated work only, so it shows these in a group
  // of their own; each add also reads the agenda and the board again in place (the board's To do gets the Task).
  const [created, setCreated] = useState<WorkTask[]>([]);
  const { sorting, unsorted, readUnsorted, openSorting, closeSorting } =
    useUnsorted({ transport, active, refreshKey, onRoute });
  const fresh = useTabFreshness({
    transport,
    active,
    sorting,
    refreshKey,
    activeTab,
    activeEntry: entries[activeTab],
    startedRef: reads.startedRef,
    orderRef: reads.orderRef,
    readAtRef: reads.readAtRef,
  });
  const { transports } = fresh;
  const searchId = useId();
  // Deeper than 1, a Task or Project is open over the list: the row, the saved views and the To sort row are hidden,
  // and Back is the first control.
  const agendaOpen = isOpenOver(ui, "agenda");
  const boardOpen = isOpenOver(ui, "board");
  const hierarchyOpen = isOpenOver(ui, "hierarchy");

  /**
   * The list of a tab showing a saved view was filtered again. When the view filtered something and every filter is
   * gone, it is the tab's own list, so the receipt is dropped; otherwise the receipt says whether the list still is the
   * view.
   */
  function listFiltersChanged(tab: SavedViewTab, filters: WorkFilters) {
    if (ui.openedViews[tab] === undefined) return;
    const applied = filtersOf(entries[tab]);
    if (Object.keys(filters).length === 0 && Object.keys(applied).length > 0) {
      void clearView(tab);
      return;
    }
    dispatchTools({
      type: "viewEdited",
      tab,
      edited: filterKey(filters) !== filterKey(applied),
    });
  }

  function renderFrame(
    tab: WorkTab,
    frame: WorkTabFrame,
    active: boolean,
  ): ReactNode {
    return (
      <WorkNewTaskContext.Provider
        value={offers("create_task") ? () => tools.openCreate(tab) : undefined}
      >
        <WorkView
          key={ui.viewKeys[tab] ?? 0}
          initial={frame}
          transport={transports[tab]}
          labels={labels}
          cardLabels={cardLabels}
          inlineLabels={inlineLabels}
          shortcuts={active}
          chrome={false}
          onOpenJournalEntry={onOpenJournalEntry}
          onRoute={onRoute}
          supportsTool={supportsTool}
          boardAvailable={offered.includes("board")}
          hierarchyQuery={
            tab === "hierarchy" ? (ui.queries.hierarchy ?? "") : undefined
          }
          refreshKey={
            (fresh.state.bumps[tab] ?? 0) +
            (tab === "board" ? fresh.state.boardTick : 0)
          }
          agendaControls={
            tab === "agenda"
              ? {
                  query: ui.queries.agenda ?? "",
                  refreshTick: fresh.state.agendaTick,
                  clear: () => tools.closeSearch("agenda"),
                }
              : undefined
          }
          onStackDepth={tools.setDepth[tab]}
          onListFilters={(filters) => {
            setListFilters((current) => ({ ...current, [tab]: filters }));
            if (tab !== "hierarchy") listFiltersChanged(tab, filters);
          }}
        />
      </WorkNewTaskContext.Provider>
    );
  }

  // A panel mounts the first time its tab is pressed and then stays mounted, hidden by the shell.
  // Shortcuts are on only for the visible panel, so a hidden view never reacts to keys.
  function panel(tab: WorkTab): ReactNode {
    return (
      <TabPanel
        key={tab}
        tab={tab}
        entry={entries[tab]}
        active={activeTab === tab && !sorting}
        shown={active}
        onLoad={reads.load}
        onRetry={retry}
        locale={locale}
      >
        {(frame, active) => renderFrame(tab, frame, active)}
      </TabPanel>
    );
  }

  // The saved views bar of the agenda and the board: the tab's own filters, and the open that reads a view.
  const savedLabels = savedViewsLabelsFor(labels.dateLocale);
  const manage = manageLabelsFor(labels.dateLocale);
  function savedBar(tab: SavedViewTab) {
    return (
      <SavedViewsBar
        tab={tab}
        transport={transport}
        labels={savedLabels}
        workLabels={labels}
        manage={manage}
        filters={listFilters[tab] ?? filtersOf(entries[tab])}
        onOpen={(definition, name) => applyView(tab, definition, name)}
      />
    );
  }
  // The new-Task field under the tab row, one per tab: closed in rest, unfolded by + (designsystem §3 "Skapa").
  const newTaskLabels = newTaskInputLabelsFor(labels.dateLocale);
  function taskCreated(task: WorkTask) {
    // The same Task twice (a retry that the server answered with the Task it already made) is listed once.
    setCreated((current) =>
      current.some((entry) => entry.id === task.id)
        ? current
        : [task, ...current],
    );
    // The shown list reads now, the others when they are pressed.
    fresh.invalidate();
    readUnsorted();
  }
  function openCreated(task: WorkTask) {
    onRoute?.({ room: "work", view: "task", id: task.id, label: task.title });
  }
  function newTaskRow(tab: WorkTab, hidden = false) {
    // In the Projects tab the new Task can go straight into a Project or Process; elsewhere it waits in To sort.
    return (
      <NewTaskInput
        id={`${searchId}${tab}-new`}
        transport={transport}
        labels={newTaskLabels}
        workLabels={labels}
        onCreated={taskCreated}
        open={Boolean(ui.createOpen[tab]) && !hidden}
        onClose={() => tools.closeCreate(tab)}
        showAdded={tab !== "agenda"}
        placeChoice={tab === "hierarchy"}
        hidden={hidden}
      />
    );
  }

  // The notes stay visible while the "⋯" panel is closed: they say what the shown list is. The receipt names the
  // opened saved view; its quiet line stays mounted so a screen reader hears each new name.
  function severalNote(tab: SavedViewTab) {
    const name = ui.openedViews[tab];
    return (
      <>
        <SavedViewReceipt
          text={
            name === undefined
              ? undefined
              : ui.editedViews[tab]
                ? savedLabels.changedFromView(name)
                : savedLabels.showingView(name)
          }
          clearLabel={savedLabels.showAll}
          failedText={savedLabels.showAllFailed}
          onClear={() => clearView(tab)}
        />
        {ui.severalPriorities[tab] ? (
          <Notice tone="warning">{savedLabels.severalPriorities}</Notice>
        ) : null}
      </>
    );
  }

  // The Work frame (.sidekick-work) holds the tab strip too, so the strip gets the app's font and colours.
  // The quiet row after the agenda shows only while some Task is unsorted and no Task is open over the list.
  const sortRow =
    unsorted && unsorted.count > 0 && !agendaOpen ? (
      <UnsortedOpenRow
        count={unsorted.count}
        more={unsorted.more}
        labels={labels}
        onOpen={openSorting}
      />
    ) : null;

  // A tab whose first read failed keeps its frame: the tab row with its tools stays, and only the list is the room's
  // error box (designsystem §3 "Tillstånd"). Uppdatera in "⋯" reads the tab again, as "Försök igen". + is off until
  // the tab's list has been read.
  const failed = (tab: WorkTab) => entries[tab]?.status === "error";
  // While a Task or Project is open over a list, its tab row shows no tools.
  const toolsShown = !isOpenOver(ui, activeTab);
  const savedViewsOffered = supportsTool?.("list_saved_work_views") !== false;
  function refresh(tab: WorkTab) {
    if (failed(tab)) retry(tab);
    else fresh.dispatch({ type: "refresh", tab });
  }
  const searchLabel = (tab: WorkTab) =>
    tab === "hierarchy" ? shellLabels.searchProjects : shellLabels.search;
  // The search field of one tab, unfolded under the tab row in place of the new-Task row.
  function search(tab: WorkTab, hidden = false) {
    return (
      <AgendaSearch
        id={`${searchId}${tab}`}
        label={searchLabel(tab)}
        closeLabel={shellLabels.closeSearch}
        query={ui.queries[tab] ?? ""}
        onQuery={(query) => tools.setQuery(tab, query)}
        open={Boolean(ui.searchOpen[tab]) && !hidden}
        focusTick={ui.searchFocus}
        onClose={() => tools.closeSearch(tab)}
      />
    );
  }
  // The "⋯" of each tab (Sparade vyer, Uppdatera, Control last), mounted on every tab and shown on its own.
  function more(tab: WorkTab) {
    return (
      <TabMore
        key={tab}
        labels={labels}
        hidden={!toolsShown || activeTab !== tab}
        open={ui.moreOpen === tab}
        onOpenChange={(open) => dispatchTools({ type: "more", tab, open })}
        onRefresh={() => refresh(tab)}
        hostSettings={hostSettings}
        onRoute={onRoute}
        supportsTool={supportsTool}
        locale={locale}
      >
        {tab === "hierarchy" || !savedViewsOffered ? null : savedBar(tab)}
      </TabMore>
    );
  }

  return (
    <div className="sidekick-work">
      {sorting ? (
        <SortingPage
          transport={transports.sorting}
          labels={labels}
          onBack={closeSorting}
        />
      ) : null}
      <div hidden={sorting}>
        <WorkShell
          labels={shellLabels}
          initialTab={initialTab}
          tabs={offered}
          onTabChange={setActiveTab}
          agenda={
            <>
              {search("agenda", agendaOpen)}
              {newTaskRow("agenda", agendaOpen)}
              {agendaOpen ? null : severalNote("agenda")}
              <RecentTasks
                tasks={created}
                labels={newTaskLabels}
                statusLabel={(status) => workStatusLabel(labels, status)}
                query={ui.queries.agenda ?? ""}
                onOpen={onRoute ? openCreated : undefined}
                hidden={agendaOpen}
              />
              {panel("agenda")}
              {sortRow}
            </>
          }
          board={
            <>
              {search("board", boardOpen)}
              {newTaskRow("board", boardOpen)}
              {boardOpen ? null : severalNote("board")}
              <BoardQuery.Provider value={ui.queries.board ?? ""}>
                <BoardClearSearch.Provider
                  value={() => tools.closeSearch("board")}
                >
                  {panel("board")}
                </BoardClearSearch.Provider>
              </BoardQuery.Provider>
            </>
          }
          hierarchy={
            <>
              {search("hierarchy", hierarchyOpen)}
              {newTaskRow("hierarchy", hierarchyOpen)}
              {panel("hierarchy")}
            </>
          }
          tabsEnd={
            <TabToolsEnd
              tools={tools}
              activeTab={activeTab}
              shown={toolsShown}
              createOff={entries[activeTab]?.status !== "ready"}
              createOffered={offers("create_task")}
              searchId={searchId}
              searchLabel={searchLabel(activeTab)}
              createLabel={newTaskLabels.field}
              menus={TABS.filter((value) => offered.includes(value)).map(more)}
            />
          }
        />
      </div>
    </div>
  );
}
