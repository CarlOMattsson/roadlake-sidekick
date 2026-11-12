import { Progress } from "../../mcp-apps/ui/progress";
import {
  hierarchyChildren,
  hierarchyItems,
  hierarchyProgress,
} from "../hierarchy/hierarchy-view";
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
 * Tasks in the frame, then up to three Projects by name, open ones first. An ended Project is not counted and
 * comes last in the list, marked with its status word ("Avslutat"); a paused one is marked "Pausat". A Project gets
 * its progress bar when the frame carries its Tasks (get_work_hierarchy with include_tasks); without them the
 * Tasks line and the bars are left out rather than shown as zero. A tree the server cut is marked with "+".
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
  const items = hierarchyItems(frame);
  const children = hierarchyChildren(items);
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
      lines={lines}
      onOpen={onOpen}
      openLabel={labels.showAll(
        openProjects.length + openProcesses.length,
        frame.truncated,
      )}
    >
      {listed.slice(0, SUMMARY_PROJECTS).map((node) => {
        const progress = hierarchyProgress(node, children);
        const mark =
          node.status && node.status !== "active"
            ? statusLabel(labels, "project", node.status)
            : undefined;
        return (
          <p key={node.id} className="work-compact-status">
            <span>{node.title}</span>
            {mark ? (
              <>
                {" "}
                <span className="work-compact-mark">· {mark}</span>
              </>
            ) : null}
            {progress ? (
              <>
                {" "}
                <Progress
                  done={progress.done}
                  total={progress.total}
                  label={labels.progressOf(progress.done, progress.total)}
                />
              </>
            ) : null}
          </p>
        );
      })}
    </ListSummary>
  );
}
