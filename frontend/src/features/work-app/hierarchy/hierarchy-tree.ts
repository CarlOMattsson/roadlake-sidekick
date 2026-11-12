import type {
  WorkHierarchyFrame,
  WorkHierarchyNode,
} from "../transport/transport";

/** Rows shown before the "+N" line in a card. The list never scrolls inside itself. */
export const HIERARCHY_MAX_ROWS = 12;

export type HierarchyProgress = { done: number; total: number };

/**
 * The tree's items: the Domains, Processes and Projects, then each Task under its Project or
 * Process followed by that Task's Steps. Tasks and Steps reuse the node shape with their own kind,
 * so one row function places them all.
 */
export function hierarchyItems(frame: WorkHierarchyFrame): WorkHierarchyNode[] {
  const items: WorkHierarchyNode[] = [...frame.nodes];
  for (const task of frame.tasks ?? []) {
    items.push({
      kind: "task",
      id: task.id,
      parent_id: task.parent_id,
      title: task.title,
      status: task.status,
      version: task.version,
    });
    for (const step of task.steps)
      items.push({
        kind: "step",
        id: step.id,
        parent_id: task.id,
        title: step.title,
        status: step.status,
      });
  }
  return items;
}

/** Children of each node on this page, in the server's order. A node whose parent is not here has no entry. */
export function hierarchyChildren(
  nodes: WorkHierarchyNode[],
): Map<string, WorkHierarchyNode[]> {
  const ids = new Set(nodes.map((node) => node.id));
  const children = new Map<string, WorkHierarchyNode[]>();
  for (const node of nodes) {
    if (node.parent_id !== null && ids.has(node.parent_id)) {
      children.set(node.parent_id, [
        ...(children.get(node.parent_id) ?? []),
        node,
      ]);
    }
  }
  return children;
}

function descendantsOf(
  node: WorkHierarchyNode,
  children: Map<string, WorkHierarchyNode[]>,
): WorkHierarchyNode[] {
  const found: WorkHierarchyNode[] = [];
  const seen = new Set<string>([node.id]);
  const pending = [...(children.get(node.id) ?? [])];
  for (let next = pending.pop(); next; next = pending.pop()) {
    if (seen.has(next.id)) continue;
    seen.add(next.id);
    found.push(next);
    pending.push(...(children.get(next.id) ?? []));
  }
  return found;
}

/**
 * Summed progress under a node. A Task counts its Steps; a Domain, Process or Project counts every
 * Task beneath it. A status of "completed" is done. Null for a Step, and for a node with nothing
 * countable under it, so no empty bar is drawn.
 */
export function hierarchyProgress(
  node: WorkHierarchyNode,
  children: Map<string, WorkHierarchyNode[]>,
): HierarchyProgress | null {
  if (node.kind === "step") return null;
  const counted = node.kind === "task" ? "step" : "task";
  const under = descendantsOf(node, children).filter(
    (item) => item.kind === counted,
  );
  if (under.length === 0) return null;
  return {
    done: under.filter((item) => item.status === "completed").length,
    total: under.length,
  };
}

/** The counts of one Project or Process from the frame's Tasks: done of all, and how many open ones are overdue. */
export type GroupCounts = { done: number; total: number; overdue: number };

/**
 * The counts of each Project and Process, by id, from the Tasks the frame carries (include_tasks). Undefined when the
 * frame has no Tasks, so a list read without them shows no counts at all rather than "no tasks". An open Task is
 * overdue when its due time has passed.
 */
export function groupCounts(
  frame: WorkHierarchyFrame,
  now: Date = new Date(),
): Map<string, GroupCounts> | undefined {
  if (!frame.tasks) return undefined;
  const counts = new Map<string, GroupCounts>();
  for (const task of frame.tasks) {
    const entry = counts.get(task.parent_id) ?? {
      done: 0,
      total: 0,
      overdue: 0,
    };
    entry.total += 1;
    if (task.status === "completed") entry.done += 1;
    else if (task.due_at && new Date(task.due_at).getTime() < now.getTime())
      entry.overdue += 1;
    counts.set(task.parent_id, entry);
  }
  return counts;
}

/** One Domain with the Projects and Processes shown under it: open Projects first, then the Processes. */
export type ProjectsSection = {
  /** Null for the groups whose Domain is not on the page (a cut page). */
  domain: WorkHierarchyNode | null;
  groups: WorkHierarchyNode[];
};

/** What the Projects list shows: a section per Domain, and the completed Projects in their own closed group last. */
export type ProjectsLayout = {
  sections: ProjectsSection[];
  completed: WorkHierarchyNode[];
};

/**
 * The Projects list from the hierarchy's nodes: each Domain in the server's order with its active and paused Projects
 * and then its Processes; completed Projects leave their Domain for the closed group last. A Project or Process whose
 * Domain is not on the page comes first, in a section with no heading. `needle` (trimmed, lower-cased) keeps the
 * groups whose title holds it, and every group of a Domain whose name holds it; a Domain with nothing kept is left out.
 */
export function projectsLayout(
  nodes: WorkHierarchyNode[],
  needle = "",
): ProjectsLayout {
  const domains = nodes.filter((node) => node.kind === "domain");
  const domainIds = new Set(domains.map((node) => node.id));
  const matches = (text: string) => text.toLocaleLowerCase().includes(needle);
  const groups = nodes.filter(
    (node) => node.kind === "project" || node.kind === "process",
  );
  const keep = (group: WorkHierarchyNode) => {
    if (!needle || matches(group.title)) return true;
    const domain = domains.find((node) => node.id === group.parent_id);
    return domain !== undefined && matches(domain.title);
  };
  const open = (group: WorkHierarchyNode) =>
    !(group.kind === "project" && group.status === "completed");
  const ordered = (list: WorkHierarchyNode[]) => [
    ...list.filter((node) => node.kind === "project"),
    ...list.filter((node) => node.kind === "process"),
  ];
  const shown = groups.filter((group) => open(group) && keep(group));
  const orphans = shown.filter(
    (group) => group.parent_id === null || !domainIds.has(group.parent_id),
  );
  const sections: ProjectsSection[] = [];
  if (orphans.length > 0)
    sections.push({ domain: null, groups: ordered(orphans) });
  for (const domain of domains) {
    const under = ordered(
      shown.filter((group) => group.parent_id === domain.id),
    );
    // Without a filter a Domain shows even when it is empty, so it can be found; a filter leaves it out.
    if (under.length > 0 || !needle) sections.push({ domain, groups: under });
  }
  return {
    sections,
    completed: groups.filter((group) => !open(group) && keep(group)),
  };
}

/**
 * The rows within the budget: open groups first, in their order, then the completed ones when their group is open.
 * `cut` is how many of a section's groups were left out; `hidden` all of them, for the "+N" line.
 */
export function limitRows(
  layout: ProjectsLayout,
  rowLimit: number,
  completedShown: boolean,
) {
  let budget = rowLimit;
  const sections: (ProjectsSection & { cut: number })[] = [];
  for (const section of layout.sections) {
    const groups = section.groups.slice(0, Math.max(0, budget));
    budget -= groups.length;
    sections.push({
      ...section,
      groups,
      cut: section.groups.length - groups.length,
    });
  }
  const completedRows = completedShown
    ? layout.completed.slice(0, Math.max(0, budget))
    : [];
  const hidden =
    sections.reduce((sum, section) => sum + section.cut, 0) +
    (completedShown ? layout.completed.length - completedRows.length : 0);
  return { sections, completedRows, hidden };
}

/** The two pages as one frame: nodes and Tasks of the next page after the shown ones (an id already shown keeps its place), and the next page's cursor and truncation. */
export function mergeHierarchyPage(
  shown: WorkHierarchyFrame,
  next: WorkHierarchyFrame,
): WorkHierarchyFrame {
  const merge = <T extends { id: string }>(known: T[], page: T[]) => {
    const seen = new Set(known.map((item) => item.id));
    return [...known, ...page.filter((item) => !seen.has(item.id))];
  };
  const merged: WorkHierarchyFrame = {
    ...shown,
    nodes: merge(shown.nodes, next.nodes),
    truncated: next.truncated,
    ...(shown.tasks || next.tasks
      ? { tasks: merge(shown.tasks ?? [], next.tasks ?? []) }
      : {}),
  };
  // The last page has no cursor: the merged frame must not keep the one that was just followed.
  if (next.next_cursor === undefined) delete merged.next_cursor;
  else merged.next_cursor = next.next_cursor;
  return merged;
}
