import type { WorkLabels } from "../shared/labels";
import "./new-task-input.css";
import { ArchivedRows, UndoLine, WriteNotice } from "../shared/manage-controls";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { RowMenuTip } from "../shared/row-menu";
import type { WorkTransport } from "../transport/transport";
import { StepCreate } from "../steps/step-create";
import { useTaskSteps } from "../steps/use-task-steps";
import { StepRow } from "./step-row";

/**
 * Steps of one Task with a checkbox per Step. Checking completes the Step; unchecking sets it
 * back to to-do through update_task_step. Every write carries the Step's current version and an
 * idempotency key that a retry of the same click reuses. Each Step row has a ⋯ button that opens its
 * Up, Down and Archive buttons; archived Steps can be restored from the Undo line or the list below.
 * A new write clears the status line and any notice; focus goes to the Undo line after an archive and
 * to the restored row after Undo.
 */
export function TaskSteps({
  taskId,
  transport,
  labels: t,
}: {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
}) {
  const offers = useToolSupport(transport);
  // What the host cannot write is not offered: the checks need both ways of the tick (complete_task_step, and
  // update_task_step for the Undo and for unchecking), the menu its Up and Down, its Archive (with restore) and its Actions.
  const canToggle = offers("complete_task_step") && offers("update_task_step");
  const canMove = offers("reorder_task_steps");
  const canArchive = offers("archive_task_step") && offers("restore_task_step");
  const canActions = offers("list_step_actions");
  const hasMenu = canMove || canArchive || canActions;
  const steps = useTaskSteps(taskId, transport, t);
  const { state, write, manage, banner, listRef, headingRef, undoBox } = steps;
  const { phase, notice, more, undo, archived, status, stepUndo } = state;
  const hasMore = state.nextCursor !== undefined;

  const failedStep =
    notice?.kind === "failed"
      ? state.steps.find((step) => step.id === notice.stepId)
      : undefined;
  // The checkboxes and the list controls wait while any write runs or the list is re-read.
  const listBusy = state.busyId !== undefined || write.busy || state.refreshing;
  const doneCount = state.steps.filter(
    (step) => step.status === "completed",
  ).length;
  // The count is left out while more Steps exist than the list holds: "2 av 4" would then be wrong.
  const heading =
    state.steps.length && !hasMore
      ? t.stepsProgress(doneCount, state.steps.length)
      : t.steps;
  // A Task with no Steps shows only "+ Lägg till steg" (F and O: an empty "Steg" section took a heading's room). The
  // heading stays for assistive technology and comes back with the first Step, an Undo line or a notice.
  const bare =
    phase === "ready" &&
    !state.steps.length &&
    !undo &&
    !archived.length &&
    !notice &&
    !write.failure;
  return (
    <section>
      <h3
        ref={headingRef}
        tabIndex={-1}
        className={bare ? "work-visually-hidden" : undefined}
      >
        {heading}
      </h3>
      <WriteNotice
        failure={write.failure}
        labels={manage}
        onReload={() => {
          write.clear();
          steps.reloadSteps();
        }}
        onRetry={steps.retryWrite}
      />
      {notice?.kind === "conflict" && (
        <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
          <p>{t.stepConflict}</p>
          <button type="button" onClick={steps.reloadSteps}>
            {t.reload}
          </button>
        </div>
      )}
      {notice?.kind === "forbidden" && <p>{t.forbiddenWrite}</p>}
      {notice?.kind === "invalid" && <p role="alert">{t.invalidChange}</p>}
      {notice?.kind === "notFound" && <p role="alert">{t.notFound}</p>}
      {failedStep && (
        <p role="alert">
          {t.stepSaveFailed}{" "}
          <button type="button" onClick={() => steps.toggle(failedStep)}>
            {t.retry}
          </button>
        </p>
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.stepsForbidden}</p>}
      {phase === "error" && (
        <p role="alert">
          {t.failed}{" "}
          <button type="button" onClick={steps.retryLoad}>
            {t.retry}
          </button>
        </p>
      )}
      {/* No "Inga steg än.": "+ Lägg till steg" under the heading already says the list is empty (§3, Tomt). */}
      {phase === "ready" && state.steps.length > 0 && (
        <ul className="work-steps" ref={listRef}>
          {state.steps.map((step, index) => (
            <StepRow
              key={step.id}
              step={step}
              index={index}
              count={state.steps.length}
              listBusy={listBusy}
              transport={transport}
              labels={t}
              manage={manage}
              onToggle={canToggle ? steps.toggle : undefined}
              undo={stepUndo?.id === step.id ? stepUndo : undefined}
              onUndo={() => stepUndo && steps.undoToggle(stepUndo)}
              onExpire={steps.expireStepUndo}
              onMove={
                canMove && !hasMore
                  ? (delta) => steps.move(step.id, delta)
                  : undefined
              }
              onArchive={canArchive ? () => steps.archive(step.id) : undefined}
              actions={canActions}
              onActionCount={(count, done) =>
                steps.setActionCount(step.id, count, done)
              }
            />
          ))}
        </ul>
      )}
      {phase === "ready" && more === "busy" && <p role="status">{t.loading}</p>}
      {phase === "ready" && more === "failed" && (
        <p role="alert">{t.stepsReadMoreFailed}</p>
      )}
      {phase === "ready" && hasMore && (
        <button
          type="button"
          disabled={more === "busy"}
          onClick={steps.loadMore}
        >
          {t.stepsShowMore}
        </button>
      )}
      {phase === "ready" && status && <p role="status">{status}</p>}
      {phase === "ready" && undo && (
        <div ref={undoBox}>
          <UndoLine
            text={manage.archived(undo.title)}
            disabled={listBusy}
            labels={manage}
            onUndo={() => steps.restore(undo)}
          />
        </div>
      )}
      {phase === "ready" && (
        <ArchivedRows
          // An archived Step joins this list only once its Undo line has gone.
          items={archived.filter((entry) => entry.id !== undo?.id)}
          disabled={listBusy}
          labels={manage}
          onRestore={(id) => {
            const item = archived.find((entry) => entry.id === id);
            if (item) steps.restore(item);
          }}
        />
      )}
      {phase === "ready" && offers("create_task_step") && (
        <StepCreate
          taskId={taskId}
          transport={transport}
          labels={t}
          onWriteStart={steps.startWrite}
          onCreated={steps.stepCreated}
        />
      )}
      {/* The tip right under "+ Lägg till steg", so the add row follows the last step. */}
      {phase === "ready" && state.steps.length > 0 && hasMenu && (
        <RowMenuTip labels={t} step />
      )}
    </section>
  );
}
