import { StatusGlyph } from "../mcp-apps/ui/status-glyph";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { workStatusLabel, type WorkLabels } from "./labels";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import "./new-task-input.css";
import { UndoMeta } from "./agenda-undo";
import {
  ArchivedRows,
  RowControls,
  UndoLine,
  WriteNotice,
  focusControl,
  focusUndoIn,
  moveItem,
} from "./manage-controls";
import { manageLabelsFor, type ManageLabels } from "./manage-labels";
import { StepActions } from "./step-actions";
import { useToolSupport } from "../mcp-apps/tool-support";
import {
  RowMenuButton,
  RowMenuTip,
  rowMenuHandlers,
  rowMenuHint,
} from "./board-card";
import { stepActionsLabelsFor } from "./step-actions-labels";
import {
  isForbidden,
  writeFailure,
  type WorkStep,
  type WorkTransport,
} from "./transport";
import { useWorkWrite } from "./use-work-write";
import { appendSteps, readSteps } from "./step-pages";
import { StepCreate } from "./step-create";

type StepsPhase = "loading" | "ready" | "forbidden" | "error";
type StepNotice =
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "invalid" }
  | { kind: "notFound" }
  | { kind: "failed"; stepId: string };

/** A Step archived during this visit, with the version its archive returned (what Restore needs). */
type ArchivedStep = {
  id: string;
  title: string;
  version: number;
  /** The place the Step had when it was archived; a restore falls back to the row now there. */
  index: number;
};
/** The list action last started, so Try again runs the same action, and the same key, once more. */
type StepAction =
  | { kind: "move"; stepId: string; delta: -1 | 1 }
  | { kind: "archive"; stepId: string }
  | { kind: "restore"; item: ArchivedStep };
/**
 * The Step checked or unchecked last: `done` is the state the check gave it, so Undo writes the other
 * state against the version the check left (`version`).
 */
type StepUndo = { id: string; title: string; version: number; done: boolean };
/** Where focus goes once React has drawn the list again. */
type FocusWish =
  | {
      kind: "row";
      stepId: string;
      prefer: "up" | "down" | "archive";
      index?: number;
    }
  | { kind: "undo" }
  | { kind: "heading" };

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
  const [phase, setPhase] = useState<StepsPhase>("loading");
  const [steps, setSteps] = useState<WorkStep[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [busyId, setBusyId] = useState<string>();
  // True while a re-read of the list is in flight; checkboxes wait for the fresh list.
  const [refreshing, setRefreshing] = useState(false);
  // Where the next page of Steps starts while the Task has more than the view has read; Show more
  // continues from it. A reorder needs every active Step, so the Up and Down controls wait for it.
  const [nextCursor, setNextCursor] = useState<string>();
  const [more, setMore] = useState<"idle" | "busy" | "failed">("idle");
  const hasMore = nextCursor !== undefined;
  const [notice, setNotice] = useState<StepNotice>();
  const banner = useRef<HTMLDivElement>(null);
  // Bumped by every list request and by every successful write. A list response that is not the
  // newest request, or that crosses a successful write, is stale and must not overwrite the list.
  const ticket = useRef(0);
  // Synchronous guard: a second click in the same tick must not start a second write.
  const writing = useRef(false);
  const pending = useRef(new Map<string, PendingKey>());
  const mounted = useRef(true);
  // Move, archive and restore: one write at a time, one key per action, the refusal sorted out.
  const write = useWorkWrite();
  const manage = manageLabelsFor(t.dateLocale);
  const [archived, setArchived] = useState<ArchivedStep[]>([]);
  // The Step archived last, whose Undo line is shown; Undo, Restore or a newer archive replaces it.
  const [undo, setUndo] = useState<ArchivedStep>();
  // The Step checked last, whose row shows Ångra until it runs out, another write, or Undo.
  const [stepUndo, setStepUndo] = useState<StepUndo>();
  const expireStepUndo = useCallback(() => setStepUndo(undefined), []);
  // The status line after a move or a restore.
  const [status, setStatus] = useState<string>();
  const listRef = useRef<HTMLUListElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const undoBox = useRef<HTMLDivElement>(null);
  const focusWish = useRef<FocusWish | undefined>(undefined);
  const lastAction = useRef<StepAction | undefined>(undefined);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const marker = ticket;
    const current = ++marker.current;
    readSteps(
      (cursor) => transport.listTaskSteps(taskId, cursor),
      () => current === marker.current,
    )
      .then((read) => {
        if (!read) return;
        // A focus wish for a row this read does not hold would wait for a row that is never drawn.
        const wish = focusWish.current;
        if (
          wish?.kind === "row" &&
          !read.items.some((step) => step.id === wish.stepId)
        ) {
          // The row is gone from the fresh list: the row now at its old place, else the heading.
          const next =
            wish.index === undefined ? undefined : read.items[wish.index];
          focusWish.current = next
            ? { kind: "row", stepId: next.id, prefer: "archive" }
            : { kind: "heading" };
        }
        setSteps(read.items);
        setNextCursor(read.cursor);
        setMore(read.failed ? "failed" : "idle");
        setRefreshing(false);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (current !== marker.current) return;
        focusWish.current = undefined;
        setRefreshing(false);
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
    return () => {
      marker.current++;
    };
  }, [transport, taskId, attempt]);
  useEffect(() => {
    if (notice?.kind === "conflict") banner.current?.focus();
  }, [notice]);
  // After React has drawn the list again, the wanted control takes focus. A row not drawn yet (a
  // restored Step before its re-read) keeps the wish until it is drawn.
  useLayoutEffect(() => {
    const wish = focusWish.current;
    if (!wish) return;
    if (wish.kind === "heading") {
      focusWish.current = undefined;
      headingRef.current?.focus();
      return;
    }
    if (wish.kind === "undo") {
      // The Undo line is drawn in the same render as the archived row's removal.
      if (focusUndoIn(undoBox.current)) focusWish.current = undefined;
      return;
    }
    const row = listRef.current;
    const drawn = row?.querySelector(
      `[data-manage^="${CSS.escape(wish.stepId)}:"]`,
    );
    if (!drawn) return;
    focusWish.current = undefined;
    // A row whose menu is closed (a restored Step) takes the focus on its check, which opens the menu.
    if (
      !row?.querySelector(`[data-manage="${CSS.escape(wish.stepId)}:archive"]`)
    ) {
      row
        ?.querySelector<HTMLButtonElement>(
          `[data-manage="${CSS.escape(wish.stepId)}:more"]`,
        )
        ?.focus();
      return;
    }
    focusControl(row, wish.stepId, wish.prefer);
  });

  /** Every write clears the status line, the notice and the Undo line of the write before it. */
  function startWrite() {
    setStatus(undefined);
    setNotice(undefined);
    setStepUndo(undefined);
  }
  function reloadSteps() {
    setNotice(undefined);
    setRefreshing(true);
    setAttempt((n) => n + 1);
  }
  function retryLoad() {
    setPhase("loading");
    setAttempt((n) => n + 1);
  }
  /**
   * Sets one Step done or to-do against the version the view holds. The signature names the action,
   * so the same Step, version and direction reuse one key. `onDone` runs once the server has answered.
   */
  function setDone(
    step: { id: string; version: number },
    complete: boolean,
    onDone: (result: WorkStep) => void,
  ) {
    if (writing.current) return;
    const signature = JSON.stringify([step.id, step.version, complete]);
    const pendingKey = keyFor(pending.current.get(step.id), signature);
    pending.current.set(step.id, pendingKey);
    writing.current = true;
    setBusyId(step.id);
    startWrite();
    const request = complete
      ? transport.completeTaskStep(step.id, step.version, pendingKey.key)
      : transport.updateTaskStep(
          step.id,
          step.version,
          { status: "todo" },
          pendingKey.key,
        );
    request
      .then((result) => {
        if (!mounted.current) return;
        pending.current.delete(step.id);
        // Any list request still in flight is older than this write: drop its response.
        ticket.current++;
        setRefreshing(false);
        setSteps((current) =>
          current.map((item) => (item.id === step.id ? result.step : item)),
        );
        onDone(result.step);
      })
      .catch((error: unknown) => {
        if (!mounted.current) return;
        const kind = writeFailure(error);
        if (kind === "conflict") setNotice({ kind: "conflict" });
        else if (kind === "forbidden") setNotice({ kind: "forbidden" });
        else if (kind === "invalid") setNotice({ kind: "invalid" });
        else if (kind === "not_found") {
          // The Step is gone: the list is read again so its row leaves, and the text says why.
          reloadSteps();
          setNotice({ kind: "notFound" });
        } else setNotice({ kind: "failed", stepId: step.id });
      })
      .finally(() => {
        writing.current = false;
        setBusyId(undefined);
      });
  }

  /** Checking completes the Step, unchecking sets it to do; the check then offers Ångra in its row. */
  function toggle(step: WorkStep) {
    const complete = step.status !== "completed";
    setDone(step, complete, (result) => {
      setStepUndo({
        id: step.id,
        title: step.title,
        version: result.version,
        done: complete,
      });
    });
  }

  /** Undo writes the other state of the check, against the version the check left. */
  function undoToggle(undoItem: StepUndo) {
    setDone(undoItem, !undoItem.done, () => undefined);
  }

  /** Moves the Step one place up or down; the whole order goes to the server with the versions held. */
  function move(stepId: string, delta: -1 | 1) {
    const index = steps.findIndex((step) => step.id === stepId);
    const step = steps[index];
    const ordered = moveItem(steps, index, delta);
    if (!step || !ordered) return;
    lastAction.current = { kind: "move", stepId, delta };
    // The signature names the new order and the versions it rests on: a Try again reuses the key.
    const signature = JSON.stringify([
      "reorder",
      taskId,
      ordered.map((item) => [item.id, item.version]),
    ]);
    startWrite();
    void write
      .run(signature, (key) =>
        transport.reorderTaskSteps(
          taskId,
          ordered.map((item) => ({ id: item.id, version: item.version })),
          key,
        ),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        // Any list request still in flight is older than this write: drop its response.
        ticket.current++;
        setRefreshing(false);
        setSteps(result.items);
        setNextCursor(undefined);
        focusWish.current = {
          kind: "row",
          stepId,
          prefer: delta < 0 ? "up" : "down",
        };
        setStatus(manage.moved(step.title, index + delta + 1, ordered.length));
      });
  }

  /** Reads the next page of Steps and adds it to the list; a failed read keeps the list and the button. */
  function loadMore() {
    if (!nextCursor || more === "busy") return;
    const current = ticket.current;
    setMore("busy");
    transport
      .listTaskSteps(taskId, nextCursor)
      .then((page) => {
        if (!mounted.current || current !== ticket.current) return;
        setSteps((known) => appendSteps(known, page.items));
        setNextCursor(page.next_cursor ?? undefined);
        setMore("idle");
      })
      .catch(() => {
        if (mounted.current && current === ticket.current) setMore("failed");
      });
  }

  /** Archives the Step (nothing is deleted) and offers Undo; focus goes to the row that took its place. */
  function archive(stepId: string) {
    const index = steps.findIndex((item) => item.id === stepId);
    const step = steps[index];
    if (!step) return;
    lastAction.current = { kind: "archive", stepId };
    const signature = JSON.stringify(["archive", step.id, step.version]);
    startWrite();
    void write
      .run(signature, (key) =>
        transport.archiveTaskStep(step.id, step.version, key),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        // Any list request still in flight is older than this write: drop its response.
        ticket.current++;
        setRefreshing(false);
        const rest = steps.filter((item) => item.id !== step.id);
        setSteps(rest);
        const item: ArchivedStep = {
          id: step.id,
          title: step.title,
          version: result.step.version,
          index,
        };
        setArchived((current) => [...current, item]);
        setUndo(item);
        focusWish.current = { kind: "undo" };
      });
  }

  /** Restores an archived Step, then reads the list again so the Step returns to its place. */
  function restore(item: ArchivedStep) {
    lastAction.current = { kind: "restore", item };
    const signature = JSON.stringify(["restore", item.id, item.version]);
    startWrite();
    void write
      .run(signature, (key) =>
        transport.restoreTaskStep(item.id, item.version, key),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        setArchived((current) =>
          current.filter((entry) => entry.id !== item.id),
        );
        setUndo((current) => (current?.id === item.id ? undefined : current));
        setStatus(manage.restored(item.title));
        focusWish.current = {
          kind: "row",
          stepId: item.id,
          prefer: "archive",
          index: item.index,
        };
        setRefreshing(true);
        setAttempt((n) => n + 1);
      });
  }

  /** Try again after a failed move, archive or restore: the same action, so the same key. */
  function retryWrite() {
    const action = lastAction.current;
    if (!action) return;
    if (action.kind === "move") move(action.stepId, action.delta);
    else if (action.kind === "archive") archive(action.stepId);
    else restore(action.item);
  }

  /** A created Step joins the end of the list with its version, so it can be checked at once. */
  function stepCreated(step: WorkStep) {
    // Any list request still in flight is older than this write: drop its response.
    ticket.current++;
    setRefreshing(false);
    setSteps((current) => [
      ...current.filter((item) => item.id !== step.id),
      step,
    ]);
    // The section's one status line: the added text replaces whatever status the last write left.
    setStatus(t.stepAdded);
  }

  const failedStep =
    notice?.kind === "failed"
      ? steps.find((step) => step.id === notice.stepId)
      : undefined;
  // The checkboxes and the list controls wait while any write runs or the list is re-read.
  const listBusy = busyId !== undefined || write.busy || refreshing;
  const doneCount = steps.filter((step) => step.status === "completed").length;
  // The count is left out while more Steps exist than the list holds: "2 av 4" would then be wrong.
  const heading =
    steps.length && !hasMore
      ? t.stepsProgress(doneCount, steps.length)
      : t.steps;
  // A Task with no Steps shows only "+ Lägg till steg" (F and O: an empty "Steg" section took a heading's room). The
  // heading stays for assistive technology and comes back with the first Step, an Undo line or a notice.
  const bare =
    phase === "ready" &&
    !steps.length &&
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
          reloadSteps();
        }}
        onRetry={retryWrite}
      />
      {notice?.kind === "conflict" && (
        <div role="alert" tabIndex={-1} ref={banner} className="work-banner">
          <p>{t.stepConflict}</p>
          <button type="button" onClick={reloadSteps}>
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
          <button type="button" onClick={() => toggle(failedStep)}>
            {t.retry}
          </button>
        </p>
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.stepsForbidden}</p>}
      {phase === "error" && (
        <p role="alert">
          {t.failed}{" "}
          <button type="button" onClick={retryLoad}>
            {t.retry}
          </button>
        </p>
      )}
      {/* No "Inga steg än.": "+ Lägg till steg" under the heading already says the list is empty (§3, Tomt). */}
      {phase === "ready" && steps.length > 0 && (
        <ul className="work-steps" ref={listRef}>
          {steps.map((step, index) => (
            <StepRow
              key={step.id}
              step={step}
              index={index}
              count={steps.length}
              listBusy={listBusy}
              transport={transport}
              labels={t}
              manage={manage}
              onToggle={canToggle ? toggle : undefined}
              undo={stepUndo?.id === step.id ? stepUndo : undefined}
              onUndo={() => stepUndo && undoToggle(stepUndo)}
              onExpire={expireStepUndo}
              onMove={
                canMove && !hasMore
                  ? (delta) => move(step.id, delta)
                  : undefined
              }
              onArchive={canArchive ? () => archive(step.id) : undefined}
              actions={canActions}
            />
          ))}
        </ul>
      )}
      {phase === "ready" && more === "busy" && <p role="status">{t.loading}</p>}
      {phase === "ready" && more === "failed" && (
        <p role="alert">{t.stepsReadMoreFailed}</p>
      )}
      {phase === "ready" && hasMore && (
        <button type="button" disabled={more === "busy"} onClick={loadMore}>
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
            onUndo={() => restore(undo)}
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
            if (item) restore(item);
          }}
        />
      )}
      {phase === "ready" && offers("create_task_step") && (
        <StepCreate
          taskId={taskId}
          transport={transport}
          labels={t}
          onWriteStart={startWrite}
          onCreated={stepCreated}
        />
      )}
      {/* The tip right under "+ Lägg till steg", so the add row follows the last step. */}
      {phase === "ready" && steps.length > 0 && hasMenu && (
        <RowMenuTip labels={t} step />
      )}
    </section>
  );
}

/** The mark of a Step the host cannot tick: a dot for an open Step, a tick without a box for a done one. Not a control. */
function StepReadMark({ done, label }: { done: boolean; label: string }) {
  return (
    <svg
      className="sk-status-glyph work-step-mark"
      viewBox="0 0 16 16"
      focusable="false"
      role="img"
      aria-label={label}
      data-glyph={done ? "step-read-check" : "step-read-dot"}
    >
      {done ? (
        <path d="M4.2 8.4L6.9 11L11.8 5.4" />
      ) : (
        <circle cx={8} cy={8} r={1.75} />
      )}
    </svg>
  );
}

/**
 * One Step of the list: the checkbox and the title, and the Step's Actions under the title. A long press (touch), a
 * right click, Shift+F10 or the menu key on the Step opens its Up, Down and Archive buttons (as Arbete's rows;
 * the ⋯ is gone), and the check says so to a screen reader (aria-keyshortcuts, aria-description). The menu stays open
 * after a move, so the focus rule keeps the moved row's Up or Down button.
 */
function StepRow({
  step,
  index,
  count,
  listBusy,
  transport,
  labels: t,
  manage,
  onToggle,
  undo,
  onUndo,
  onExpire,
  onMove,
  onArchive,
  actions,
}: {
  step: WorkStep;
  index: number;
  count: number;
  listBusy: boolean;
  transport: WorkTransport;
  labels: WorkLabels;
  manage: ManageLabels;
  /** Absent: the Step is shown, not checked (the host cannot complete it). */
  onToggle?: (step: WorkStep) => void;
  /** The check this row was just given: its meta line says "Klar" or "Öppen igen" and Ångra stands in the row. */
  undo?: StepUndo;
  onUndo: () => void;
  onExpire: () => void;
  /** Absent: no Up and Down. */
  onMove?: (delta: -1 | 1) => void;
  /** Absent: no Archive. */
  onArchive?: () => void;
  /** False: no "Visa åtgärder". With no menu entry at all, the Step has no menu (no long press, no hint). */
  actions: boolean;
}) {
  const hasMenu = Boolean(onMove || onArchive || actions);
  const [open, setOpen] = useState(false);
  // The Step's Actions open from this menu; they stay open until the menu's button closes them.
  const [actionsOpen, setActionsOpen] = useState(false);
  const s = stepActionsLabelsFor(t.dateLocale);
  return (
    <li
      className={
        [
          step.status === "completed" && "work-step-done",
          undo && "work-step-undoing",
        ]
          .filter(Boolean)
          .join(" ") || undefined
      }
      {...(hasMenu ? rowMenuHandlers(open, setOpen) : {})}
    >
      {onToggle ? (
        <label>
          {/* The native box is kept for its semantics and keys, but drawn as the app's Step square in the text
              colour (Chromium's blue box was the only system control on the screen); the input covers the whole label. */}
          <input
            type="checkbox"
            className="work-step-check"
            data-manage={`${step.id}:more`}
            aria-keyshortcuts={hasMenu ? "Shift+F10" : undefined}
            {...(hasMenu ? { "aria-description": rowMenuHint(t, true) } : {})}
            checked={step.status === "completed"}
            disabled={listBusy}
            onChange={() => onToggle(step)}
          />
          <StatusGlyph kind="step" status={step.status} />
          <span>{step.title}</span>
        </label>
      ) : (
        // The host cannot tick a Step: it is text with its state in words, not a box that looks pressable. An open Step has
        // a neutral dot, a done one a bare tick (the muted tick of the done ring, without its frame).
        <div className="work-step-read">
          <StepReadMark
            done={step.status === "completed"}
            label={workStatusLabel(t, step.status)}
          />
          <span>{step.title}</span>
        </div>
      )}
      {undo && (
        // A new check gets a new key, so its Ångra starts its own time.
        <UndoMeta
          key={`${undo.id}:${undo.version}`}
          text={undo.done ? t.stepDone : t.stepReopened}
          labels={t}
          disabled={listBusy}
          onUndo={onUndo}
          onExpire={onExpire}
        />
      )}
      {hasMenu && open && (
        <div className="work-step-menu">
          <RowControls
            id={step.id}
            title={step.title}
            index={index}
            count={count}
            disabled={listBusy}
            labels={manage}
            onMove={onMove}
            onArchive={onArchive}
          />
          {actions && (
            <button
              type="button"
              className="sk-btn sk-btn--quiet work-step-actions-open"
              aria-expanded={actionsOpen}
              onClick={() => setActionsOpen((value) => !value)}
            >
              {actionsOpen ? s.hide : s.show}
            </button>
          )}
        </div>
      )}
      {actions && (
        <StepActions
          step={step}
          transport={transport}
          labels={t}
          open={actionsOpen}
        />
      )}
      {hasMenu && (
        <RowMenuButton
          label={t.rowMenuButton(step.title)}
          open={() => setOpen(true)}
          firstChoice=".work-step-menu button:not(:disabled)"
        />
      )}
    </li>
  );
}
