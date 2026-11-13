import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { taskStatusLabel, type WorkLabels } from "../shared/labels";
import {
  ArchivedRows,
  RowControls,
  UndoLine,
  WriteNotice,
  focusControl,
  focusUndoIn,
  moveItem,
} from "../shared/manage-controls";
import { manageLabelsFor } from "../shared/manage-labels";
import { stepActionsLabelsFor } from "./step-actions-labels";
import {
  isForbidden,
  type WorkAction,
  type WorkStep,
  type WorkTransport,
} from "../transport/transport";
import { useWorkWrite } from "../shared/use-work-write";
import "./step-actions.css";

export type StepActionsProps = {
  step: WorkStep;
  transport: WorkTransport;
  labels: WorkLabels;
  /** Shown by the Step's ⋯ menu ("Visa åtgärder"); nothing is drawn while it is false. */
  open: boolean;
  /** Called with the number of active Actions after each read and each archive, so the Step's row can follow it. */
  onCount: (count: number) => void;
};

type ActionsPhase = "idle" | "ready" | "forbidden" | "error";
/** An archived Action kept for this visit, with the version the archive answered. */
type ArchivedAction = {
  id: string;
  title: string;
  version: number;
  /** The place the Action had when it was archived; a restore falls back to the row now there. */
  index: number;
};

/**
 * The Actions of one Step. The Step's ⋯ menu opens them (`open`), so a Step without Actions shows no
 * control of its own. The list is read when they open, not with the Step, so a closed Step costs no
 * request. Up and Down reorder the whole list
 * with reorderStepActions (every active Action once, with the version the view holds); Archive is
 * taken back by its Undo line, or later by Restore under the list. Every answer from an older read
 * is dropped once a write has succeeded, so the list never falls back to a state the server left.
 * A new write clears the status line. Focus goes to the Undo line after an archive, and back to the
 * restored row after Undo.
 */
export function StepActions({
  step,
  transport,
  labels: t,
  open,
  onCount,
}: StepActionsProps) {
  const manage = manageLabelsFor(t.dateLocale);
  const s = stepActionsLabelsFor(t.dateLocale);
  const write = useWorkWrite();
  const [reading, setReading] = useState(false);
  const [phase, setPhase] = useState<ActionsPhase>("idle");
  const [actions, setActions] = useState<WorkAction[]>([]);
  const [archived, setArchived] = useState<ArchivedAction[]>([]);
  const [undoId, setUndoId] = useState<string>();
  const [notice, setNotice] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const undoBox = useRef<HTMLDivElement>(null);
  // Set by a write, run once the list has been drawn again with the rows it holds (see the layout effect).
  const pendingFocus = useRef<((rows: WorkAction[]) => void) | undefined>(
    undefined,
  );
  // The write the user last started, so the WriteNotice retry runs the same action again.
  const lastWrite = useRef<(() => void) | undefined>(undefined);
  // Bumped by every list request and by every successful write. A list answer that is not the
  // newest request, or that crosses a successful write, is stale and must not overwrite the list.
  const ticket = useRef(0);
  const mounted = useRef(true);
  // The newest callback, read when an answer arrives; it is no dependency, so a new one starts no new read.
  const countRef = useRef(onCount);
  useEffect(() => {
    countRef.current = onCount;
  }, [onCount]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // Focus goes to a row only after the list holding it has been drawn, never on a timer.
  useLayoutEffect(() => {
    const focus = pendingFocus.current;
    pendingFocus.current = undefined;
    focus?.(actions);
  }, [actions]);

  /** Drops any read still in flight and ends the reading state; called by every successful write. */
  function settle() {
    ticket.current++;
    setReading(false);
  }

  const loadActions = useCallback(() => {
    const current = ++ticket.current;
    setReading(true);
    transport
      .listStepActions(step.id)
      .then((page) => {
        if (current !== ticket.current || !mounted.current) return;
        setActions(page.items);
        setPhase("ready");
        setReading(false);
        countRef.current(page.items.length);
      })
      .catch((error: unknown) => {
        if (current !== ticket.current || !mounted.current) return;
        pendingFocus.current = undefined;
        setPhase(isForbidden(error) ? "forbidden" : "error");
        setReading(false);
      });
  }, [transport, step.id]);
  // The list is read each time the Actions open, as the disclosure did; a closed Step makes no request.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reading on open sets its loading state first, by design.
    if (open) loadActions();
  }, [open, loadActions]);

  async function moveAction(index: number, delta: -1 | 1) {
    const moved = actions[index];
    const next = moveItem(actions, index, delta);
    if (!moved || !next) return;
    lastWrite.current = () => void moveAction(index, delta);
    setNotice("");
    const result = await write.run(
      JSON.stringify([
        "reorder-actions",
        step.id,
        next.map((item) => [item.id, item.version]),
      ]),
      (key) =>
        transport.reorderStepActions(
          step.id,
          next.map((item) => ({ id: item.id, version: item.version })),
          key,
        ),
    );
    if (!result || !mounted.current) return;
    settle();
    pendingFocus.current = () =>
      focusControl(listRef.current, moved.id, delta < 0 ? "up" : "down");
    setActions(result.items);
    setNotice(
      manage.moved(moved.title, index + delta + 1, result.items.length),
    );
  }

  async function archiveAction(action: WorkAction) {
    const index = actions.findIndex((item) => item.id === action.id);
    if (index < 0) return;
    lastWrite.current = () => void archiveAction(action);
    setNotice("");
    const result = await write.run(
      JSON.stringify(["archive-action", action.id, action.version]),
      (key) => transport.archiveStepAction(action.id, action.version, key),
    );
    if (!result || !mounted.current) return;
    settle();
    const remaining = actions.filter((item) => item.id !== action.id);
    // Focus goes to the Undo line of the archived row, the same rule as every other list.
    pendingFocus.current = () => {
      focusUndoIn(undoBox.current);
    };
    setActions(remaining);
    countRef.current(remaining.length);
    setArchived((list) => [
      ...list,
      {
        id: action.id,
        title: action.title,
        version: result.action.version,
        index,
      },
    ]);
    setUndoId(action.id);
  }

  async function restoreAction(id: string) {
    const item = archived.find((entry) => entry.id === id);
    if (!item) return;
    lastWrite.current = () => void restoreAction(id);
    setNotice("");
    const result = await write.run(
      JSON.stringify(["restore-action", item.id, item.version]),
      (key) => transport.restoreStepAction(item.id, item.version, key),
    );
    if (!result || !mounted.current) return;
    settle();
    setArchived((list) => list.filter((entry) => entry.id !== id));
    setUndoId((current) => (current === id ? undefined : current));
    setNotice(manage.restored(item.title));
    // The re-read puts the Action back in its place; the layout effect then focuses its row.
    pendingFocus.current = (rows) => {
      const target = rows.find((row) => row.id === id) ?? rows[item.index];
      if (target) focusControl(listRef.current, target.id, "archive");
    };
    loadActions();
  }

  function reloadActions() {
    write.clear();
    loadActions();
  }

  const undoItem = archived.find((entry) => entry.id === undoId);
  // Nothing is drawn while closed, but the archived Actions and the Undo line are kept for the visit.
  if (!open) return null;
  return (
    <section
      className="work-step-actions"
      aria-label={s.sectionFor(step.title)}
    >
      <div className="work-step-actions-body">
        {phase === "ready" && actions.length > 0 && (
          <p className="work-step-actions-count">
            {s.countHeading(actions.length)}
          </p>
        )}
        {reading && <p role="status">{t.loading}</p>}
        {!reading && phase === "forbidden" && <p>{s.forbidden}</p>}
        {!reading && phase === "error" && (
          <p role="alert">
            {t.failed}{" "}
            <button type="button" onClick={loadActions}>
              {t.retry}
            </button>
          </p>
        )}
        {phase === "ready" &&
          (actions.length ? (
            <ul ref={listRef} className="work-step-actions-list">
              {actions.map((action, index) => (
                <li key={action.id} className="work-step-action">
                  <div className="work-step-action-text">
                    <span className="work-step-action-title">
                      {action.title}
                    </span>
                    <span className="work-step-action-status">
                      {taskStatusLabel(t, action.status)}
                    </span>
                  </div>
                  <RowControls
                    id={action.id}
                    title={action.title}
                    index={index}
                    count={actions.length}
                    disabled={write.busy || reading}
                    labels={manage}
                    onMove={(delta) => {
                      void moveAction(index, delta);
                    }}
                    onArchive={() => {
                      void archiveAction(action);
                    }}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <p>{s.none}</p>
          ))}
        <p role="status" className="work-step-actions-notice">
          {notice}
        </p>
        <WriteNotice
          failure={write.failure}
          labels={manage}
          onReload={reloadActions}
          onRetry={() => lastWrite.current?.()}
        />
        {undoItem && (
          <div ref={undoBox}>
            <UndoLine
              text={manage.archived(undoItem.title)}
              disabled={write.busy || reading}
              labels={manage}
              onUndo={() => {
                void restoreAction(undoItem.id);
              }}
            />
          </div>
        )}
        <ArchivedRows
          // An archived Action joins this list only once its Undo line has gone.
          items={archived.filter((entry) => entry.id !== undoId)}
          disabled={write.busy || reading}
          labels={manage}
          onRestore={(id) => {
            void restoreAction(id);
          }}
        />
      </div>
    </section>
  );
}
