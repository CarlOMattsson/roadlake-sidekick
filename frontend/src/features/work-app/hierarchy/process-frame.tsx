import { useCallback, useState } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { hierarchyStatusLabel, knownLabel } from "../shared/labels";
import { CreateParentTask } from "./parent-task-create";
import type {
  WorkProcessRecord,
  WorkTaskSummary,
} from "../transport/transport";
import { DetailBar } from "../view/parts/detail-bar";
import { FrameMeta } from "../view/parts/frame-meta";
import type { FrameProps } from "../view/parts/frame-types";
import { processFrameLabelsFor } from "./process-frame-labels";
import { TaskSummaryList } from "../tasks/task-summary-list";
import {
  useDetailFrame,
  useFrameRead,
  usePagedSection,
} from "../view/parts/use-detail-frame";
import { useDomainName } from "../view/parts/use-domain-name";

/**
 * A Process page, the sibling of ProjectFrame: kicker, name, a line "Hem · Varje vecka" (the Area and the cadence),
 * the status when it is not active, the description and the Tasks of the Process with "+ Ny uppgift". The Process
 * itself is read only here; the Tasks section loads and fails on its own.
 */
export function ProcessFrame({
  id,
  transport,
  labels: t,
  moves,
  onOpen,
  refreshKey = 0,
  back,
}: FrameProps & { id: string }) {
  const pl = processFrameLabelsFor(t.dateLocale);
  const frame = useDetailFrame({ moves });
  const { phase, heading } = frame;
  const [process, setProcess] = useState<WorkProcessRecord>();
  // The phone's host answers Project task lists only: there the section is a calm line, and nothing is created.
  const offers = useToolSupport(transport);
  const tasksOffered = offers("list_tasks", { process_id: id });
  const createOffered = offers("create_task");
  const domainName = useDomainName(transport, process?.domain_id);
  useFrameRead(
    frame,
    useCallback(() => transport.getProcess(id), [transport, id]),
    (result) => setProcess(result.process),
    refreshKey,
  );
  const tasks = usePagedSection<WorkTaskSummary>({
    list: useCallback(
      (...after: [] | [string]) => transport.listProcessTasks(id, ...after),
      [transport, id],
    ),
    enabled: tasksOffered,
    refreshKey,
  });
  /** A created Task goes to the top of the list; the list itself is not read again. */
  function taskCreated(task: WorkTaskSummary) {
    // A read that started before the Task was made would answer without it: it is dropped.
    tasks.invalidate();
    tasks.setItems((known) => [
      task,
      ...known.filter((item) => item.id !== task.id),
    ]);
  }
  return (
    <article className="work-process">
      <DetailBar
        back={back}
        kicker={phase !== "gone" ? pl.process : undefined}
      />
      <h2 ref={heading} tabIndex={-1} className="work-detail-title">
        {phase === "ready" && process ? process.name : pl.process}
      </h2>
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "error" && (
        <section className="sk-card">
          <p className="sk-eyebrow">{t.title}</p>
          <ErrorNotice
            locale={t.dateLocale}
            cause={frame.readError}
            onRetry={frame.retry}
          />
        </section>
      )}
      {phase === "gone" && <p role="status">{pl.gone}</p>}
      {phase === "ready" && process && (
        <>
          <FrameMeta
            area={domainName}
            detail={
              process.cadence
                ? knownLabel(pl.cadence, process.cadence)
                : undefined
            }
          />
          {process.status !== "active" && (
            <p className="work-chip">
              {t.status}: {hierarchyStatusLabel(t, "process", process.status)}
            </p>
          )}
          {process.description && (
            <p className="work-description">{process.description}</p>
          )}
          <h3>{t.tasks}</h3>
          {!tasksOffered && <p>{pl.tasksUnavailable}</p>}
          {tasksOffered && tasks.phase === "loading" && (
            <p role="status">{t.loading}</p>
          )}
          {tasksOffered && tasks.phase === "forbidden" && (
            <p>{pl.tasksForbidden}</p>
          )}
          {tasksOffered && tasks.phase === "error" && (
            <p role="alert">
              {t.failed}{" "}
              <button type="button" onClick={tasks.retry}>
                {t.retry}
              </button>
            </p>
          )}
          {tasksOffered && tasks.phase === "ready" && (
            <>
              {createOffered ? (
                <CreateParentTask
                  parent={{ process_id: process.id }}
                  transport={transport}
                  labels={t}
                  onCreated={taskCreated}
                />
              ) : null}
              <TaskSummaryList
                tasks={tasks.items}
                labels={t}
                empty={pl.noTasks}
                onOpen={onOpen}
                transport={transport}
              />
              {tasks.more === "busy" && <p role="status">{t.loading}</p>}
              {tasks.more === "failed" && <p role="alert">{t.failed}</p>}
              {tasks.truncated && !tasks.nextCursor && (
                <p role="note">{pl.tasksTruncated}</p>
              )}
              {tasks.nextCursor && (
                <button
                  type="button"
                  disabled={tasks.more === "busy"}
                  onClick={tasks.loadMore}
                >
                  {t.more}
                </button>
              )}
            </>
          )}
        </>
      )}
    </article>
  );
}
