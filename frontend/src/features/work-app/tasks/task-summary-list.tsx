import { useContext, useRef, useState } from "react";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { TagChips } from "../../mcp-apps/ui/tags";
import { KnownTags } from "../shared/work-tags";
import { fillLabel } from "../agenda/agenda-undo";
import { taskStatusLabel, type WorkLabels } from "../shared/labels";
import { WriteNotice } from "../shared/manage-controls";
import { manageLabelsFor } from "../shared/manage-labels";
import { OpenChevron, RowUndo } from "./task-detail-controls";
import {
  isTaskStatus,
  type TaskStatusValue,
  type WorkFrame,
  type WorkTaskSummary,
  type WorkTransport,
} from "../transport/transport";
import { useWorkWrite } from "../shared/use-work-write";
import { TaskDue } from "./task-due";

/**
 * Task summaries as the shared task row (the board's and the agenda's): the status ring, the title that opens the
 * Task, and under it one meta line, (the status and how late it is) and two of its tags. The status is named only when the ring does not say
 * it (not `todo`), there is no `status` prefix, and the date is plain text. In a detail view the row ends in › like
 * the note and Project rows beside it (§3, Chevronregeln): the title opens the Task and, with `transport`, the ring
 * marks it done. The row then
 * stays with a filled ring and `completed` with `undo` while Ångra holds (§3, Ångra).
 */
export function TaskSummaryList({
  tasks,
  labels: t,
  empty,
  onOpen,
  transport,
  onReload,
}: {
  tasks: WorkTaskSummary[];
  labels: WorkLabels;
  empty: string;
  onOpen: (frame: WorkFrame, label?: string) => void;
  transport?: WorkTransport;
  onReload?: () => void;
}) {
  const write = useWorkWrite();
  const known = useContext(KnownTags);
  const [rung, setRung] = useState<
    Record<
      string,
      {
        status: TaskStatusValue;
        from: TaskStatusValue;
        version: number;
        undo: boolean;
      }
    >
  >({});
  const again = useRef<() => void>(undefined);
  /** Writes `status` from the ring (or its Ångra) against the version the row was read with, then the one it got. */
  function ring(task: WorkTaskSummary, status: TaskStatusValue, undo: boolean) {
    if (!transport) return;
    again.current = () => ring(task, status, undo);
    const known = rung[task.id];
    void write
      .run(JSON.stringify([task.id, status]), (key) =>
        transport.updateTask(
          task.id,
          // get_contact_context and list_tasks carry each Task's version.
          known?.version ?? (task as { version?: number }).version ?? 0,
          { status },
          key,
        ),
      )
      .then((result) => {
        if (result)
          setRung((all) => ({
            ...all,
            [task.id]: {
              status,
              from:
                known?.from ??
                (isTaskStatus(task.status) ? task.status : "todo"),
              version: result.task.version,
              undo,
            },
          }));
      });
  }
  if (!tasks.length) return <p>{empty}</p>;
  return (
    <>
      <ul className="work-list">
        {tasks.map((task) => {
          const entry = rung[task.id];
          const status = entry?.status ?? task.status;
          const done = status === "completed";
          const statusText = taskStatusLabel(t, status);
          const showStatus = status !== "todo" && !done;
          const showDue = Boolean(task.due_at) && !done;
          const tags = task.tags ?? [];
          const glyph = (
            <StatusGlyph kind="task" status={status} label={statusText} />
          );
          return (
            <li key={task.id} className="work-agenda-row work-open-row">
              <div className="work-agenda-line">
                {transport ? (
                  <button
                    type="button"
                    className="work-agenda-glyph"
                    aria-label={fillLabel(
                      done ? t.agendaReopen : t.agendaComplete,
                      { title: task.title },
                    )}
                    disabled={write.busy}
                    onClick={() =>
                      ring(task, done ? "todo" : "completed", !done)
                    }
                  >
                    {glyph}
                  </button>
                ) : (
                  <span className="work-agenda-glyph">{glyph}</span>
                )}
                <div className="work-agenda-body">
                  <button
                    type="button"
                    onClick={() =>
                      onOpen({ kind: "task", id: task.id }, task.title)
                    }
                  >
                    {task.title}
                  </button>
                  {entry?.undo ? (
                    <p role="status" className="work-card-meta">
                      {statusText}
                    </p>
                  ) : showDue || showStatus || done || tags.length > 0 ? (
                    <p className="work-card-meta">
                      {showDue && task.due_at && (
                        <span className="work-card-due">
                          <TaskDue dueAt={task.due_at} labels={t} />
                        </span>
                      )}
                      {showStatus && <span>{statusText}</span>}
                      {done && <span>{statusText}</span>}
                      <TagChips
                        tags={tags}
                        known={known}
                        max={2}
                        locale={t.dateLocale}
                      />
                    </p>
                  ) : // No meta to show: no empty line under the title, so a one-line row is as tall as the Agenda's.
                  null}
                </div>
                {entry?.undo ? (
                  <RowUndo
                    label={t.agendaUndo}
                    disabled={write.busy}
                    onUndo={() => ring(task, entry.from, false)}
                    onExpire={() =>
                      setRung((all) => ({
                        ...all,
                        [task.id]: { ...entry, undo: false },
                      }))
                    }
                  />
                ) : (
                  <OpenChevron />
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <WriteNotice
        failure={write.failure}
        labels={manageLabelsFor(t.dateLocale)}
        onReload={() => {
          write.clear();
          onReload?.();
        }}
        onRetry={() => again.current?.()}
      />
    </>
  );
}
