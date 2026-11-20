import { useEffect, useMemo, useRef, type ReactNode } from "react";
import type { WorkLabels } from "../shared/labels";
import "./new-task-input.css";
import { ArchivedRows, UndoLine, WriteNotice } from "../shared/manage-controls";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { RowMenuTip } from "../shared/row-menu";
import { rowReceipt, useUndoReceipts } from "../shared/use-undo-receipts";
import type { WorkStep, WorkTransport } from "../transport/transport";
import { StepCreate } from "../steps/step-create";
import { useTaskSteps } from "../steps/use-task-steps";
import { StepRow } from "./step-row";

/**
 * Steps of one Task with a checkbox per Step. Checking completes the Step; unchecking sets it
 * back to to-do through update_task_step. Every write carries the Step's current version and an
 * idempotency key that a retry of the same click reuses. Each Step row has a ⋯ button that opens its
 * Up, Down and Archive buttons; archived Steps can be restored from the Undo line or the list below.
 * A new write clears the status line and any notice; focus goes to the Undo line after an archive and
 * to the restored row after Undo. A check keeps its row's new state ("Klar") and is confirmed, with Ångra, in the
 * view's receipt bar (`receipt`), so the row has no button of its own and the list never moves.
 */
export function TaskSteps({
  taskId,
  transport,
  labels: t,
  receipt,
  stepExtra,
  refreshKey = 0,
}: {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
  /** The Task view's one receipt bar, where the Steps' and their Actions' checks are confirmed. */
  receipt: ReceiptState;
  /** What the Task adds under a Step's title (an AI Step's run to review). */
  stepExtra?: (step: WorkStep) => ReactNode;
  /** A new value reads the Steps again in place (a reviewed AI Step moved on the server). */
  refreshKey?: number;
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
  const { state, write, manage, listRef, headingRef, undoBox } = steps;
  const { phase, notice, more, undo, archived, status, stepUndo } = state;
  const hasMore = state.nextCursor !== undefined;
  // The check just made: "Klar: {title}" with Ångra in the bar; the row keeps its state until the bar's time is up.
  const stepUndos = useMemo(
    () => (stepUndo ? { [stepUndo.id]: stepUndo } : {}),
    [stepUndo],
  );
  useUndoReceipts({
    undos: stepUndos,
    receipt,
    describe: (_key, undo) => ({
      message: rowReceipt(undo.done ? t.stepDone : t.stepReopened, undo.title),
      undo: { label: t.agendaUndo, onUndo: () => steps.undoToggle(undo) },
    }),
    onEnd: steps.expireStepUndo,
  });
  // Only a new key reads again: the first render keeps the list the hook is already reading.
  const reloadSteps = useRef(steps.reloadSteps);
  const seenKey = useRef(refreshKey);
  useEffect(() => {
    reloadSteps.current = steps.reloadSteps;
  });
  useEffect(() => {
    if (refreshKey === seenKey.current) return;
    seenKey.current = refreshKey;
    reloadSteps.current();
  }, [refreshKey]);

  const failedStep =
    notice?.kind === "failed"
      ? state.steps.find((step) => step.id === notice.stepId)
      : undefined;
  // The write the Task refused, in words; a failed tick has its own line with Försök igen.
  const refusal =
    notice?.kind === "invalid"
      ? t.invalidChange
      : notice?.kind === "notFound"
        ? t.notFound
        : undefined;
  // The checkboxes and the list controls wait while any write runs or the list is re-read.
  const listBusy = state.busyId !== undefined || write.busy || state.refreshing;
  // Who does each Step is said only in a Task where some Step is done by AI; elsewhere every Step is the owner's.
  const marked = state.steps.some((step) => step.performer === "ai");
  const doneCount = state.steps.filter(
    (step) => step.status === "completed",
  ).length;
  // The count is left out while more Steps exist than the list holds: the count would then be wrong.
  const heading =
    state.steps.length && !hasMore
      ? t.stepsProgress(doneCount, state.steps.length)
      : t.steps;
  // A Task with no Steps shows only `addStep` (F and O: an empty `steps` section took a heading's room). The
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
      {notice?.kind === "forbidden" && <p>{t.forbiddenWrite}</p>}
      {refusal && (
        <ErrorNotice placement="row" locale={t.dateLocale} message={refusal} />
      )}
      {failedStep && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={t.stepSaveFailed}
          onRetry={() => steps.toggle(failedStep)}
        />
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.stepsForbidden}</p>}
      {phase === "error" && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          onRetry={steps.retryLoad}
        />
      )}
      {/* No `noSteps` line: `addStep` under the heading already says the list is empty (§3, Tomt). */}
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
              receipt={receipt}
              undo={stepUndo?.id === step.id ? stepUndo : undefined}
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
              marked={marked}
              extra={stepExtra?.(step)}
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
      {/* The tip right under `addStep`, so the add row follows the last step. */}
      {phase === "ready" && state.steps.length > 0 && hasMenu && (
        <RowMenuTip labels={t} step />
      )}
    </section>
  );
}
