import { Progress } from "../../mcp-apps/ui/progress";
import {
  hierarchyChildren,
  hierarchyItems,
  hierarchyProgress,
} from "../hierarchy/hierarchy-view";
import { hierarchyDetailLabelsFor } from "../hierarchy/hierarchy-detail-labels";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import type {
  WorkHierarchyFrame,
  WorkHierarchyNode,
} from "../transport/transport";
import {
  ListSummary,
  statusLabel,
  type CountLine,
} from "./inline-summary-list";

/** Projects named in the hierarchy summary. The rest are counted only. */
const SUMMARY_PROJECTS = 3;

/** A Project or Process that has ended: the card does not count it and lists it last, marked. */
function isEnded(node: WorkHierarchyNode): boolean {
  return node.status === "completed" || node.status === "archived";
}

/**
 * Inline hierarchy: the number of open Projects (active or paused), of open Processes when there are any, and of
 * Tasks in the frame, then up to three Projects by name, open ones first, each in the rows' one template: the name,
 * and under it the meta line. An ended Project is not counted and comes last in the list, marked with its status word
 * ("Avslutat"); a paused one is marked "Pausat". A Project gets its progress ("0 av 1 klara" and the bar), or "Inga
 * uppgifter än", when the frame carries its Tasks (get_work_hierarchy with include_tasks); without them the Tasks line
 * and the progress are left out rather than shown as zero. The rows are text, not buttons, so they carry no ›: "Öppna
 * Projekt" opens the Projects. A tree the server cut is marked with "+". Without a single Project, Process or Domain the card is
 * the room's empty state and its link, with no counts.
 */
export function HierarchySummary({
  frame,
  labels,
  onOpen,
}: {
  frame: WorkHierarchyFrame;
  labels: InlineSummaryLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
}) {
  const projects = frame.nodes.filter((node) => node.kind === "project");
  const openProjects = projects.filter((node) => !isEnded(node));
  const openProcesses = frame.nodes.filter(
    (node) => node.kind === "process" && !isEnded(node),
  );
  // Array.prototype.sort is stable: open Projects keep the server's order, then the ended ones.
  const listed = [...projects].sort(
    (a, b) => Number(isEnded(a)) - Number(isEnded(b)),
  );
  const dl = hierarchyDetailLabelsFor(labels.dateLocale);
  const items = hierarchyItems(frame);
  const children = hierarchyChildren(items);
  const blank = frame.nodes.length === 0 && !frame.truncated;
  const lines: CountLine[] = [
    {
      key: "projects",
      label: labels.projectCount,
      count: openProjects.length,
      more: frame.truncated,
      text: labels.projectsCount(openProjects.length, frame.truncated),
    },
  ];
  if (openProcesses.length > 0)
    lines.push({
      key: "processes",
      label: labels.processCount,
      count: openProcesses.length,
      more: frame.truncated,
      text: labels.processesCount(openProcesses.length, frame.truncated),
    });
  if (frame.tasks)
    lines.push({
      key: "tasks",
      label: labels.taskCount,
      count: frame.tasks.length,
      more: frame.truncated,
      text: labels.tasksCount(frame.tasks.length, frame.truncated),
    });
  return (
    <ListSummary
      labels={labels}
      kindLabel={labels.kind.hierarchy}
      className="work-compact-hierarchy"
      lines={lines}
      blank={blank ? labels.blank.hierarchy : undefined}
      onOpen={onOpen}
      openLabel={labels.openHierarchy}
      aside={labels.moreRows(
        Math.max(0, listed.length - SUMMARY_PROJECTS),
        frame.truncated,
      )}
    >
      <ul className="work-compact-rows">
        {listed.slice(0, SUMMARY_PROJECTS).map((node) => {
          const progress = hierarchyProgress(node, children);
          const mark =
            node.status && node.status !== "active"
              ? statusLabel(labels, "project", node.status)
              : undefined;
          // Without the frame's Tasks nothing is known of the progress, so the line says nothing rather than "none".
          const empty = frame.tasks && !progress ? dl.noTasks : undefined;
          return (
            <li key={node.id} className="work-compact-row">
              <span className="work-compact-row-title">{node.title}</span>
              {mark || progress || empty ? (
                <span className="work-compact-row-meta">
                  {mark ? (
                    <span className="work-compact-mark">{mark}</span>
                  ) : null}
                  {progress ? (
                    <Progress
                      done={progress.done}
                      total={progress.total}
                      label={labels.progressOf(progress.done, progress.total)}
                    />
                  ) : null}
                  {empty ? <span>{empty}</span> : null}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </ListSummary>
  );
}
