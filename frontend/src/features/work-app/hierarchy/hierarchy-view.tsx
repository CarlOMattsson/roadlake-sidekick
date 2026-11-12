import { useRef, useState } from "react";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { useShortcuts } from "../../mcp-apps/ui/shortcuts";
import { hierarchyDetailLabelsFor } from "./hierarchy-detail-labels";
import { DomainAccent, GroupRow } from "./hierarchy-group-row";
import {
  HIERARCHY_MAX_ROWS,
  groupCounts,
  limitRows,
  projectsLayout,
} from "./hierarchy-tree";
import { hierarchyStatusLabel, type WorkLabels } from "../shared/labels";
import type {
  WorkFrame,
  WorkHierarchyFrame,
  WorkHierarchyNode,
  WorkTransport,
} from "../transport/transport";
import { useHierarchyMore, useHierarchyRefresh } from "./use-hierarchy-feed";
import "../agenda/agenda.css";
import "./hierarchy.css";

// The tree helpers live in hierarchy-tree.ts; the list's callers and tests import them from here.
export {
  HIERARCHY_MAX_ROWS,
  groupCounts,
  hierarchyChildren,
  hierarchyItems,
  hierarchyProgress,
  mergeHierarchyPage,
  projectsLayout,
} from "./hierarchy-tree";
export type {
  GroupCounts,
  HierarchyProgress,
  ProjectsLayout,
  ProjectsSection,
} from "./hierarchy-tree";

function rowButtons(list: HTMLElement | null): HTMLButtonElement[] {
  return list
    ? Array.from(
        list.querySelectorAll<HTMLButtonElement>(
          ".work-tree-open, .work-tree-fold",
        ),
      )
    : [];
}

/**
 * The Projects tab: the user's Projects and Processes, the two ways of grouping Tasks, under the name of their Domain.
 * A Domain's open Projects come first, then its Processes (the word "Process" on the meta line); the completed Projects
 * sit in a closed group last, opened by a tap anywhere on its row. A row shows how far the Project has come ("1 av 3
 * klara") and how many of its Tasks are overdue, when the frame carries the Tasks (the tab reads it with
 * include_tasks). A tap on a row opens the Project's or Process's page through `onOpen`, with its Tasks, "+ Ny
 * uppgift" and its own Back.
 *
 * The rows are plain buttons in the tab order. `shortcuts` adds the window keys j and k (move focus between rows); only
 * a fullscreen caller passes it. Without `query` the view has its own title filter; the tab row's search gives one.
 */
export function HierarchyView({
  frame,
  transport,
  onChange,
  stale = false,
  onRead,
  refreshKey,
  labels: t,
  shortcuts = false,
  rowLimit = HIERARCHY_MAX_ROWS,
  headingHidden = true,
  query: given,
  onOpen,
}: {
  frame: WorkHierarchyFrame;
  /** Reads the list again in place (get_work_hierarchy); absent, the view shows `frame` as it is. */
  transport?: WorkTransport;
  /** Takes the frame of a read again; the caller puts it in place of `frame`. */
  onChange?: (next: WorkHierarchyFrame) => void;
  /** A Task was saved on a page opened from this list: the list reads again once when it is shown. */
  stale?: boolean;
  /** Called after a read, so the caller clears its `stale` mark. */
  onRead?: () => void;
  /** A changed value reads the list again in place (the value at mount is not a request). */
  refreshKey?: number;
  labels: WorkLabels;
  shortcuts?: boolean;
  /** Most Project and Process rows shown before the "+N" line. Fullscreen passes Infinity. */
  rowLimit?: number;
  /** False in a card: the list says "Projekt" in a heading of its own. */
  headingHidden?: boolean;
  /** The filter text of the tab row's search (fullscreen). Given, the view shows no filter field of its own. */
  query?: string;
  /** Opens a Project or Process page (the work view's stack, or the shell's when the host routes). */
  onOpen?: (frame: WorkFrame, label?: string) => void;
}) {
  const dl = hierarchyDetailLabelsFor(t.dateLocale);
  const [ownQuery, setQuery] = useState("");
  const [completedOpen, setCompletedOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const query = given ?? ownQuery;
  useHierarchyRefresh({
    frame,
    transport,
    onChange,
    stale,
    onRead,
    refreshKey,
  });
  const paging = useHierarchyMore({ frame, transport, onChange, refreshKey });
  const needle = query.trim().toLocaleLowerCase();
  const counts = groupCounts(frame);
  const layout = projectsLayout(frame.nodes, needle);
  const titleOf = new Map(frame.nodes.map((node) => [node.id, node.title]));
  // A filter that keeps completed Projects shows them at once.
  const completedShown =
    completedOpen || (needle !== "" && layout.completed.length > 0);

  const { sections, completedRows, hidden } = limitRows(
    layout,
    rowLimit,
    completedShown,
  );
  const nothing =
    layout.completed.length === 0 &&
    layout.sections.every(
      (section) => section.groups.length === 0 && (needle || !section.domain),
    );

  function moveFocus(delta: number) {
    const buttons = rowButtons(listRef.current);
    if (buttons.length === 0) return;
    const index = buttons.findIndex(
      (button) => button === document.activeElement,
    );
    const next = Math.min(Math.max(index + delta, 0), buttons.length - 1);
    buttons[next]?.focus();
  }
  useShortcuts(
    { j: () => moveFocus(1), k: () => moveFocus(-1) },
    { enabled: shortcuts },
  );

  const row = (node: WorkHierarchyNode, domainTitle?: string) => (
    <GroupRow
      key={node.id}
      node={node}
      counts={
        counts && (counts.get(node.id) ?? { done: 0, total: 0, overdue: 0 })
      }
      domainTitle={domainTitle}
      t={t}
      dl={dl}
      onOpen={onOpen}
    />
  );

  return (
    <section className="sidekick-hierarchy" aria-label={t.hierarchy}>
      {headingHidden ? null : <h2>{t.hierarchy}</h2>}
      {given === undefined && (
        <div className="hierarchy-toolbar">
          <label className="work-agenda-filter">
            <span>{dl.filter}</span>
            <input
              type="search"
              aria-label={dl.filter}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>
      )}
      {nothing ? (
        <p className="work-tree-empty">
          {needle
            ? paging.offered
              ? dl.noMatchesLoaded
              : dl.noMatches
            : t.hierarchyEmpty}
        </p>
      ) : (
        <div ref={listRef} className="work-tree">
          {sections.map((section) =>
            section.domain === null ? (
              <ul key="orphans" className="work-list">
                {section.groups.map((node) => row(node))}
              </ul>
            ) : (
              <section
                key={section.domain.id}
                className="work-tree-domain"
                aria-labelledby={`work-tree-${section.domain.id}`}
              >
                <h3
                  id={`work-tree-${section.domain.id}`}
                  className="work-agenda-group work-tree-heading"
                >
                  <DomainAccent node={section.domain} />
                  {section.domain.title}
                  {section.domain.status !== undefined &&
                  section.domain.status !== "active" ? (
                    <span className="work-tree-heading-status">
                      {hierarchyStatusLabel(t, "domain", section.domain.status)}
                    </span>
                  ) : null}
                </h3>
                {section.groups.length > 0 ? (
                  <ul className="work-list">
                    {section.groups.map((node) => row(node))}
                  </ul>
                ) : section.cut === 0 ? (
                  <p className="work-tree-none">{dl.noGroups}</p>
                ) : null}
              </section>
            ),
          )}
          {layout.completed.length > 0 && (
            <section className="work-tree-completed">
              <button
                type="button"
                className="work-tree-fold"
                aria-expanded={completedShown}
                onClick={() => setCompletedOpen(!completedShown)}
              >
                <span className="work-tree-fold-label">
                  {dl.completedGroup(layout.completed.length)}
                </span>
                <span className="work-tree-fold-icon" aria-hidden="true">
                  <ChevronDownIcon />
                </span>
              </button>
              {completedRows.length > 0 && (
                <ul className="work-list">
                  {completedRows.map((node) =>
                    row(
                      node,
                      node.parent_id === null
                        ? undefined
                        : titleOf.get(node.parent_id),
                    ),
                  )}
                </ul>
              )}
            </section>
          )}
        </div>
      )}
      {hidden > 0 && (
        <p
          role="note"
          className="hierarchy-more"
          aria-label={t.hierarchyMoreLabel(hidden)}
          title={t.hierarchyMoreLabel(hidden)}
        >
          {t.hierarchyMore(hidden)}
        </p>
      )}
      {paging.more === "busy" && <p role="status">{t.loading}</p>}
      {paging.more === "failed" && <p role="alert">{t.failed}</p>}
      {paging.offered && hidden === 0 ? (
        <button
          type="button"
          className="hierarchy-load-more"
          disabled={paging.more === "busy"}
          onClick={paging.loadMore}
        >
          {t.more}
        </button>
      ) : (
        frame.truncated && <p>{t.hierarchyTruncated}</p>
      )}
    </section>
  );
}
