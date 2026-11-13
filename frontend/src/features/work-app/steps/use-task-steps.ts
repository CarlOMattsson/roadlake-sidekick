import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
} from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import type { WorkLabels } from "../shared/labels";
import { focusControl, focusUndoIn, moveItem } from "../shared/manage-controls";
import { manageLabelsFor } from "../shared/manage-labels";
import { useSingleFlight } from "../shared/use-single-flight";
import { useWorkWrite } from "../shared/use-work-write";
import {
  isForbidden,
  writeFailure,
  type WorkStep,
  type WorkTransport,
} from "../transport/transport";
import { readSteps } from "./step-pages";
import {
  initialStepsState,
  stepsReducer,
  type ArchivedStep,
  type StepUndo,
} from "./steps-state";

/** The list action last started, so Try again runs the same action, and the same key, once more. */
type StepAction =
  | { kind: "move"; stepId: string; delta: -1 | 1 }
  | { kind: "archive"; stepId: string }
  | { kind: "restore"; item: ArchivedStep };
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
 * The list of one Task's Steps and every write on it: checking, moving, archiving and restoring a Step, adding one,
 * and reading more. Every write carries the Step's current version and an idempotency key that a retry of the same
 * click reuses. A new write clears the status line and any notice; focus goes to the Undo line after an archive and
 * to the restored row after Undo.
 */
export function useTaskSteps(
  taskId: string,
  transport: WorkTransport,
  t: WorkLabels,
) {
  const [state, dispatch] = useReducer(stepsReducer, initialStepsState);
  const { steps, notice, nextCursor, attempt } = state;
  const banner = useRef<HTMLDivElement>(null);
  // Bumped by every list request and by every successful write. A list response that is not the
  // newest request, or that crosses a successful write, is stale and must not overwrite the list.
  const ticket = useRef(0);
  // Synchronous guard: a second click in the same tick must not start a second write.
  const flight = useSingleFlight();
  const pending = useRef(new Map<string, PendingKey>());
  const mounted = useRef(true);
  // Move, archive and restore: one write at a time, one key per action, the refusal sorted out.
  const write = useWorkWrite();
  // One "Show more" page per read generation, claimed before React re-renders the button.
  const pages = useSingleFlight();
  const manage = manageLabelsFor(t.dateLocale);
  const expireStepUndo = useCallback(
    () => dispatch({ type: "stepUndoSet", stepUndo: undefined }),
    [],
  );
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
        dispatch({
          type: "loaded",
          items: read.items,
          cursor: read.cursor,
          failed: read.failed,
        });
      })
      .catch((error: unknown) => {
        if (current !== marker.current) return;
        focusWish.current = undefined;
        dispatch({ type: "loadFailed", forbidden: isForbidden(error) });
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

  function startWrite() {
    dispatch({ type: "writeStarted" });
  }
  /** Any list request still in flight is older than a write that succeeded: its response is dropped. */
  function supersedeReads() {
    ticket.current++;
  }
  function reloadSteps() {
    dispatch({ type: "reload" });
  }
  function retryLoad() {
    dispatch({ type: "retryLoad" });
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
    if (!flight.enter()) return;
    const signature = JSON.stringify([step.id, step.version, complete]);
    const pendingKey = keyFor(pending.current.get(step.id), signature);
    pending.current.set(step.id, pendingKey);
    dispatch({ type: "checkStarted", id: step.id });
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
        supersedeReads();
        dispatch({ type: "checked", step: result.step });
        onDone(result.step);
      })
      .catch((error: unknown) => {
        if (!mounted.current) return;
        const kind = writeFailure(error);
        if (kind === "conflict")
          dispatch({ type: "noticed", notice: { kind: "conflict" } });
        else if (kind === "forbidden")
          dispatch({ type: "noticed", notice: { kind: "forbidden" } });
        else if (kind === "invalid")
          dispatch({ type: "noticed", notice: { kind: "invalid" } });
        else if (kind === "not_found") dispatch({ type: "notFound" });
        else
          dispatch({
            type: "noticed",
            notice: { kind: "failed", stepId: step.id },
          });
      })
      .finally(() => {
        flight.leave();
        dispatch({ type: "checkSettled" });
      });
  }

  /** Checking completes the Step, unchecking sets it to do; the check then offers Ångra in its row. */
  function toggle(step: WorkStep) {
    const complete = step.status !== "completed";
    setDone(step, complete, (result) => {
      dispatch({
        type: "stepUndoSet",
        stepUndo: {
          id: step.id,
          title: step.title,
          version: result.version,
          done: complete,
        },
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
        supersedeReads();
        focusWish.current = {
          kind: "row",
          stepId,
          prefer: delta < 0 ? "up" : "down",
        };
        dispatch({
          type: "reordered",
          items: result.items,
          status: manage.moved(step.title, index + delta + 1, ordered.length),
        });
      });
  }

  /** Reads the next page of Steps and adds it to the list; a failed read keeps the list and the button. */
  function loadMore() {
    const current = ticket.current;
    if (!nextCursor || !pages.enter(current)) return;
    dispatch({ type: "moreStarted" });
    transport
      .listTaskSteps(taskId, nextCursor)
      .then((page) => {
        if (!mounted.current || current !== ticket.current) return;
        dispatch({
          type: "moreLoaded",
          items: page.items,
          cursor: page.next_cursor ?? undefined,
        });
      })
      .catch(() => {
        if (mounted.current && current === ticket.current)
          dispatch({ type: "moreFailed" });
      })
      .finally(() => pages.leave(current));
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
        supersedeReads();
        focusWish.current = { kind: "undo" };
        dispatch({
          type: "archived",
          item: {
            id: step.id,
            title: step.title,
            version: result.step.version,
            index,
          },
        });
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
        focusWish.current = {
          kind: "row",
          stepId: item.id,
          prefer: "archive",
          index: item.index,
        };
        dispatch({
          type: "restored",
          item,
          status: manage.restored(item.title),
        });
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
    supersedeReads();
    // The section's one status line: the added text replaces whatever status the last write left.
    dispatch({ type: "created", step, status: t.stepAdded });
  }

  /** The Step's Actions were read or changed: the row offers "Visa åtgärder" only while there are some. */
  const setActionCount = useCallback(
    (stepId: string, count: number, done: number) =>
      dispatch({ type: "actionsCounted", stepId, count, done }),
    [],
  );

  return {
    state,
    write,
    manage,
    banner,
    listRef,
    headingRef,
    undoBox,
    expireStepUndo,
    startWrite,
    reloadSteps,
    retryLoad,
    toggle,
    undoToggle,
    move,
    loadMore,
    archive,
    restore,
    retryWrite,
    stepCreated,
    setActionCount,
  };
}
