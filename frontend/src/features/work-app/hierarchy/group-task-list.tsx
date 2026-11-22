import { useMemo, useState } from "react";
import { Fold } from "../../mcp-apps/ui/fold";
import { TagChips } from "../../mcp-apps/ui/tags";
import type { TagOption } from "../../mcp-apps/ui/tag-vocabulary";
import type { WorkLabels } from "../shared/labels";
import { TaskSummaryList } from "../tasks/task-summary-list";
import type {
  WorkFrame,
  WorkTaskSummary,
  WorkTransport,
} from "../transport/transport";
import { hierarchyDetailLabelsFor } from "./hierarchy-detail-labels";
import { orderGroupTasks } from "./group-task-order";

/**
 * The Tasks of a Project or Process page in the order a person works them: the open ones by due date (overdue first, no
 * date last), and the completed ones in a closed "Klara (n)" fold at the end, with no fold when none is completed.
 * The grouping follows the status the list was read with, so a Task just ticked off stays in its place under its
 * Ångra, and moves into the fold the next time the list is read; the list never jumps under the finger.
 * `hideTags` are left off the rows (the page says them once, see GroupSharedTags).
 */
export function GroupTaskList({
  tasks,
  labels,
  empty,
  onOpen,
  transport,
  onReload,
  hideTags,
}: {
  tasks: WorkTaskSummary[];
  labels: WorkLabels;
  empty: string;
  onOpen: (frame: WorkFrame, label?: string) => void;
  transport?: WorkTransport;
  onReload?: () => void;
  hideTags?: readonly string[];
}) {
  const dl = hierarchyDetailLabelsFor(labels.dateLocale);
  const [doneOpen, setDoneOpen] = useState(false);
  const { open, done } = useMemo(() => orderGroupTasks(tasks), [tasks]);
  const shared = { labels, onOpen, transport, onReload, hideTags };
  return (
    <>
      {open.length > 0 || done.length === 0 ? (
        <TaskSummaryList tasks={open} empty={empty} {...shared} />
      ) : null}
      {done.length > 0 ? (
        <>
          <Fold
            text={dl.doneTasks(done.length)}
            open={doneOpen}
            onToggle={() => setDoneOpen(!doneOpen)}
          />
          {doneOpen ? (
            <TaskSummaryList tasks={done} empty={empty} {...shared} />
          ) : null}
        </>
      ) : null}
    </>
  );
}

/** The tags every Task of the page has, said once in the page's meta instead of on each row. */
export function GroupSharedTags({
  tags,
  known,
  labels,
}: {
  tags: readonly string[];
  known?: readonly TagOption[];
  labels: WorkLabels;
}) {
  if (tags.length === 0) return null;
  const dl = hierarchyDetailLabelsFor(labels.dateLocale);
  return (
    <p className="work-card-meta work-group-shared-tags">
      <span>{dl.onAllTasks}</span>
      <TagChips tags={tags} known={known} locale={labels.dateLocale} />
    </p>
  );
}
