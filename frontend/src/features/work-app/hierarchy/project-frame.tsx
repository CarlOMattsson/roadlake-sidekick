import { useCallback, useId, useRef, useState } from "react";
import { workDate } from "../../mcp-apps/ui/due";
import { Progress } from "../../mcp-apps/ui/progress";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { projectStatusLabel } from "../shared/labels";
import { DetailMenu } from "../../mcp-apps/ui/detail-menu";
import { MoreIcon } from "../tasks/task-detail-controls";
import { ProjectEditor } from "./project-edit";
import { CreateParentTask } from "./parent-task-create";
import type {
  WorkProject,
  WorkProjectChanges,
  WorkTaskSummary,
} from "../transport/transport";
import { DetailBar } from "../view/parts/detail-bar";
import { DetailTitle } from "../view/parts/detail-title";
import { FrameMeta } from "../view/parts/frame-meta";
import type { FrameProps } from "../view/parts/frame-types";
import { TaskSummaryList } from "../tasks/task-summary-list";
import {
  useDetailFrame,
  useFrameRead,
  usePagedSection,
} from "../view/parts/use-detail-frame";
import { useDomainName } from "../view/parts/use-domain-name";
import { WriteStatus } from "../view/parts/write-status";
import { TagField } from "../../mcp-apps/ui/tags";
import { KnownTags, useWorkTags } from "../shared/work-tags";

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
  // The ⋯ in the Back row holds `edit`, as a Task's and a Contact's do; a tap on the title edits too.
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const moreButton = useRef<HTMLButtonElement>(null);
  const createOffered = offers("create_task");
  const domainName = useDomainName(transport, project?.domain_id);
  // The vocabulary labels the Project's tags and its Tasks' tags; a failed tag change keeps its retry here.
  const tags = useWorkTags(transport, "project");
  const retryTags = useRef<(() => void) | undefined>(undefined);
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
    setMenuOpen(false);
    frame.setWrite({ kind: "idle" });
    frame.setEditing(true);
  }
  /** Writes only the changed fields against the version the view holds; the key follows the action. */
  function saveProject(changes: WorkProjectChanges) {
    if (!project || frame.flight.isRunning()) return;
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
  /** Writes the Project's whole tag set (update_project changes.tags) in place; `done` runs once it is stored. */
  function setTags(next: string[], done: () => void) {
    if (!project || frame.flight.isRunning()) return;
    retryTags.current = () => setTags(next, done);
    frame.sendWrite(
      JSON.stringify(["tags", project.id, project.version, next]),
      "write",
      (key) =>
        transport.updateProject(
          project.id,
          project.version,
          { tags: next },
          key,
        ),
      (result) => {
        retryTags.current = undefined;
        setProject(result.project);
        tags.refresh();
        done();
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
    <article className="work-project">
      <DetailBar
        back={back}
        kicker={phase !== "gone" ? t.project : undefined}
        actions={
          phase === "ready" && project && editOffered ? (
            <button
              ref={moreButton}
              type="button"
              className="sk-iconbtn work-detail-action"
              aria-label={t.moreActions}
              aria-expanded={menuOpen}
              aria-controls={menuOpen ? menuId : undefined}
              disabled={write.kind === "busy" || editing}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <MoreIcon />
            </button>
          ) : undefined
        }
      />
      <DetailTitle
        heading={heading}
        onEdit={
          phase === "ready" &&
          project &&
          editOffered &&
          !editing &&
          write.kind !== "busy"
            ? startEdit
            : undefined
        }
      >
        {phase === "ready" && project ? project.title : t.project}
      </DetailTitle>
      {phase === "ready" && project && editOffered && menuOpen && (
        <DetailMenu
          id={menuId}
          busy={write.kind === "busy" || editing}
          edit={{ label: t.edit, onChoose: startEdit }}
          onClose={() => {
            setMenuOpen(false);
            moreButton.current?.focus();
          }}
        />
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "error" && (
        <ErrorNotice
          locale={t.dateLocale}
          subject="work:project"
          cause={frame.readError}
          onRetry={frame.retry}
        />
      )}
      {phase === "gone" && <p role="status">{t.goneProject}</p>}
      {phase === "ready" && project && (
        <>
          {/* While the editor is open it is the page's content: the values it edits are not drawn twice above it. */}
          {!editing && (
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
              {/* The dates are plain meta text, one line: the pill shape belongs to the tags below. */}
              {(project.start_date || project.target_date) && (
                <p className="work-card-meta work-project-dates">
                  {project.start_date && (
                    <span>
                      {t.startDate}:{" "}
                      <time dateTime={project.start_date}>
                        {workDate(
                          project.start_date,
                          new Date(),
                          t.dateLocale,
                          {
                            inline: true,
                          },
                        )}
                      </time>
                    </span>
                  )}
                  {project.target_date && (
                    <span>
                      {t.targetDate}:{" "}
                      <time dateTime={project.target_date}>
                        {workDate(
                          project.target_date,
                          new Date(),
                          t.dateLocale,
                          { inline: true },
                        )}
                      </time>
                    </span>
                  )}
                </p>
              )}
              {/* The tags under the dates, as on a Task: the pills and one quiet button that edits them in place. */}
              <TagField
                tags={project.tags ?? []}
                suggestions={tags.suggestions}
                editable={editOffered}
                busy={write.kind === "busy"}
                name={project.title}
                onChange={setTags}
                locale={t.dateLocale}
              />
              {project.description && (
                <p className="work-description">{project.description}</p>
              )}
            </>
          )}
          {write.kind === "failed" && write.action === "write" && (
            <ErrorNotice
              placement="row"
              locale={t.dateLocale}
              message={t.saveFailed}
              onRetry={() => retryTags.current?.()}
            />
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
          ) : null}
          <h3>{t.tasks}</h3>
          {tasks.phase === "loading" && <p role="status">{t.loading}</p>}
          {tasks.phase === "forbidden" && <p>{t.tasksForbidden}</p>}
          {tasks.phase === "error" && (
            <ErrorNotice
              placement="row"
              locale={t.dateLocale}
              onRetry={tasks.retry}
            />
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
              <KnownTags.Provider value={tags.suggestions}>
                <TaskSummaryList
                  tasks={tasks.items}
                  labels={t}
                  empty={t.noProjectTasks}
                  onOpen={onOpen}
                  transport={transport}
                  onReload={reloadProject}
                />
              </KnownTags.Provider>
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
