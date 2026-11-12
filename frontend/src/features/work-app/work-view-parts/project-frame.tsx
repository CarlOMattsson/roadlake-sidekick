import { useCallback, useState } from "react";
import { workDate } from "../../mcp-apps/ui/due";
import { Progress } from "../../mcp-apps/ui/progress";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { projectStatusLabel } from "../labels";
import { ProjectEditor } from "../project-edit";
import { CreateParentTask } from "../parent-task-create";
import type {
  WorkProject,
  WorkProjectChanges,
  WorkTaskSummary,
} from "../transport";
import { DetailBar } from "./detail-bar";
import { FrameMeta } from "./frame-meta";
import type { FrameProps } from "./frame-types";
import { TaskSummaryList } from "./task-summary-list";
import {
  useDetailFrame,
  useFrameRead,
  usePagedSection,
} from "./use-detail-frame";
import { useDomainName } from "./use-domain-name";
import { WriteStatus } from "./write-status";

export function ProjectFrame({
  id,
  transport,
  labels: t,
  moves,
  onOpen,
  refreshKey = 0,
  back,
}: FrameProps & { id: string }) {
  const frame = useDetailFrame({ moves });
  const { phase, write, editing, heading, banner } = frame;
  const [project, setProject] = useState<WorkProject>();
  // What the host cannot write is not offered: the phone reads a Project and its Tasks, it does not edit the Project
  // or create a Task here yet.
  const offers = useToolSupport(transport);
  const editOffered = offers("update_project");
  const createOffered = offers("create_task");
  const domainName = useDomainName(transport, project?.domain_id);
  useFrameRead(
    frame,
    useCallback(() => transport.getProject(id), [transport, id]),
    (result) => setProject(result.project),
    refreshKey,
  );
  // The Tasks section loads and fails on its own; the Project itself stays visible.
  const tasks = usePagedSection<WorkTaskSummary>({
    list: useCallback(
      (...after: [] | [string]) => transport.listProjectTasks(id, ...after),
      [transport, id],
    ),
    refreshKey,
  });
  /** A created Task goes to the top of the list; the list itself is not read again. */
  function taskCreated(task: WorkTaskSummary) {
    // A read of the list that started before the Task was made would answer without it: it is dropped,
    // and a "Show more" page on its way with it (its busy state is cleared here).
    tasks.invalidate();
    tasks.setItems((known) => [
      task,
      ...known.filter((item) => item.id !== task.id),
    ]);
  }
  function startEdit() {
    frame.setWrite({ kind: "idle" });
    frame.setEditing(true);
  }
  /** Writes only the changed fields against the version the view holds; the key follows the action. */
  function saveProject(changes: WorkProjectChanges) {
    if (!project || frame.writing.current) return;
    if (Object.keys(changes).length === 0) {
      frame.stopEdit();
      return;
    }
    frame.sendWrite(
      JSON.stringify([project.id, project.version, changes]),
      "save",
      (key) =>
        transport.updateProject(project.id, project.version, changes, key),
      (result) => {
        setProject(result.project);
        frame.setEditing(false);
        heading.current?.focus();
      },
    );
  }
  /** Fetches the latest Project; the open editor keeps the values the user typed. */
  function reloadProject() {
    frame.reload(
      () => transport.getProject(id),
      (result) => setProject(result.project),
    );
  }
  return (
    <article>
      <DetailBar
        back={back}
        kicker={phase !== "gone" ? t.project : undefined}
      />
      <h2 ref={heading} tabIndex={-1} className="work-detail-title">
        {phase === "ready" && project ? project.title : t.project}
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
      {phase === "gone" && <p role="status">{t.goneProject}</p>}
      {phase === "ready" && project && (
        <>
          <FrameMeta
            area={domainName}
            detail={
              project.tasks_total ? (
                <Progress
                  done={project.tasks_done ?? 0}
                  total={project.tasks_total}
                  label={t.progressOf(
                    project.tasks_done ?? 0,
                    project.tasks_total,
                  )}
                />
              ) : undefined
            }
          />
          {project.status !== "active" && (
            <p className="work-chip">
              {t.status}: {projectStatusLabel(t, project.status)}
            </p>
          )}
          {project.start_date && (
            <p className="work-chip">
              {t.startDate}:{" "}
              <time dateTime={project.start_date}>
                {workDate(project.start_date, new Date(), t.dateLocale)}
              </time>
            </p>
          )}
          {project.target_date && (
            <p className="work-chip">
              {t.targetDate}:{" "}
              <time dateTime={project.target_date}>
                {workDate(project.target_date, new Date(), t.dateLocale)}
              </time>
            </p>
          )}
          {project.description && (
            <p className="work-description">{project.description}</p>
          )}
          <WriteStatus
            write={write}
            conflict={t.projectConflict}
            onReload={reloadProject}
            banner={banner}
            labels={t}
          />
          {editing ? (
            <ProjectEditor
              project={project}
              busy={write.kind === "busy"}
              saveFailed={write.kind === "failed" && write.action === "save"}
              onSave={saveProject}
              onCancel={frame.stopEdit}
              labels={t}
            />
          ) : editOffered ? (
            <p>
              <button
                type="button"
                disabled={write.kind === "busy"}
                onClick={startEdit}
              >
                {t.edit}
              </button>
            </p>
          ) : null}
          <h3>{t.tasks}</h3>
          {tasks.phase === "loading" && <p role="status">{t.loading}</p>}
          {tasks.phase === "forbidden" && <p>{t.tasksForbidden}</p>}
          {tasks.phase === "error" && (
            <p role="alert">
              {t.failed}{" "}
              <button type="button" onClick={tasks.retry}>
                {t.retry}
              </button>
            </p>
          )}
          {tasks.phase === "ready" && (
            <>
              {createOffered ? (
                <CreateParentTask
                  parent={{ project_id: project.id }}
                  transport={transport}
                  labels={t}
                  onCreated={taskCreated}
                />
              ) : null}
              <TaskSummaryList
                tasks={tasks.items}
                labels={t}
                empty={t.noProjectTasks}
                onOpen={onOpen}
                transport={transport}
                onReload={reloadProject}
              />
              {tasks.more === "busy" && <p role="status">{t.loading}</p>}
              {tasks.more === "failed" && <p role="alert">{t.failed}</p>}
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
