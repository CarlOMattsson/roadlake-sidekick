import { useEffect, useId, useRef, useState } from "react";
import type { WorkLabels } from "../shared/labels";
import {
  isCompleteDate,
  titleProblem,
  type TitleProblem,
} from "../shared/fields";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { WriteFailureRow } from "../shared/write-failure-row";
import { useSingleFlight } from "../shared/use-single-flight";
import { dueAtFromDateInput } from "../tasks/task-edit";
import {
  writeFailure,
  type WorkTask,
  type WorkTaskSummary,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";

/** What the new Task belongs to: a Project or a Process (create_task takes one of project_id and process_id). */
export type TaskParent = { project_id: string } | { process_id: string };

type CreateProblem = TitleProblem | "dueIncomplete";
type CreateNotice =
  | { kind: "created" }
  | { kind: "failed"; failure: WriteFailure };

function summaryOf(task: WorkTask): WorkTaskSummary {
  return {
    id: task.id,
    title: task.title,
    status: task.status,
    due_at: task.due_at,
  };
}

/**
 * Creates a Task in the Project or Process with create_task. The created Task is handed to the parent, which
 * puts it at the top of the list. Submitting the same title and due date again reuses one key, so
 * a retry after a lost response replays the result instead of creating a second Task.
 */
export function CreateParentTask({
  parent,
  transport,
  labels: t,
  onCreated,
}: {
  parent: TaskParent;
  transport: WorkTransport;
  labels: WorkLabels;
  onCreated: (task: WorkTaskSummary) => void;
}) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  // Set while the date input holds a partial entry the browser cannot read.
  const [dueIncomplete, setDueIncomplete] = useState(false);
  const [problem, setProblem] = useState<CreateProblem>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<CreateNotice>();
  // Closed, the section shows one quiet `newTask` line; opening it puts the focus in the name.
  const [open, setOpen] = useState(false);
  const titleInput = useRef<HTMLInputElement>(null);
  const dueInput = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const dueId = useId();
  const titleErrorId = useId();
  const dueErrorId = useId();
  // Synchronous guard against a second create before React re-renders.
  const flight = useSingleFlight();
  const pendingWrite = useRef<PendingKey | undefined>(undefined);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (open) titleInput.current?.focus();
  }, [open]);
  const titleBad = problem === "required" || problem === "tooLong";
  const dueBad = problem === "dueIncomplete";

  /** Closes the form and drops what was typed in it; a create already running still finishes. */
  function close() {
    setOpen(false);
    setTitle("");
    setDue("");
    setDueIncomplete(false);
    setProblem(undefined);
    setNotice(undefined);
  }

  if (!open)
    return (
      <div>
        {/* The add row of the room's lists (`addStep`): the + in the rings' column, the words on the titles' x. */}
        <button
          type="button"
          className="work-add-row sk-action-row"
          onClick={() => setOpen(true)}
        >
          <PlusIcon />
          {t.newTask}
        </button>
      </div>
    );

  // Save runs from the button's click, not the form's submit event: the App iframe is sandboxed
  // without allow-forms, where the browser never dispatches submit. Enter still clicks the button.
  function submit() {
    if (flight.isRunning()) return;
    const titleFound = titleProblem(title);
    if (titleFound) {
      setProblem(titleFound);
      titleInput.current?.focus();
      return;
    }
    if (dueIncomplete || (due !== "" && !isCompleteDate(due))) {
      setProblem("dueIncomplete");
      dueInput.current?.focus();
      return;
    }
    const body = {
      title: title.trim(),
      ...parent,
      due_at: dueAtFromDateInput(due),
    };
    const signature = JSON.stringify([body.title, body.due_at]);
    const pendingKey = keyFor(pendingWrite.current, signature);
    pendingWrite.current = pendingKey;
    flight.enter();
    setBusy(true);
    setProblem(undefined);
    setNotice(undefined);
    transport
      .createTask(body, pendingKey.key)
      .then((result) => {
        if (!mounted.current) return;
        pendingWrite.current = undefined;
        setTitle("");
        setDue("");
        setDueIncomplete(false);
        setNotice({ kind: "created" });
        onCreated(summaryOf(result.task));
        titleInput.current?.focus();
      })
      .catch((error: unknown) => {
        if (mounted.current)
          setNotice({ kind: "failed", failure: writeFailure(error) });
      })
      .finally(() => {
        flight.leave();
        if (mounted.current) setBusy(false);
      });
  }

  return (
    <div>
      <form className="work-edit" aria-label={t.newTask} noValidate>
        <label htmlFor={titleId}>{t.newTaskTitle}</label>
        <input
          id={titleId}
          ref={titleInput}
          type="text"
          value={title}
          disabled={busy}
          aria-invalid={titleBad ? true : undefined}
          aria-describedby={titleBad ? titleErrorId : undefined}
          onChange={(event) => {
            setProblem(undefined);
            setTitle(event.target.value);
          }}
        />
        {titleBad && (
          <p id={titleErrorId}>
            {problem === "required" ? t.titleRequired : t.titleTooLong}
          </p>
        )}
        <label htmlFor={dueId}>{t.newTaskDue}</label>
        <input
          id={dueId}
          ref={dueInput}
          type="date"
          value={due}
          disabled={busy}
          aria-invalid={dueBad ? true : undefined}
          aria-describedby={dueBad ? dueErrorId : undefined}
          onChange={(event) => {
            setProblem(undefined);
            setDue(event.target.value);
            setDueIncomplete(event.target.validity.badInput);
          }}
        />
        {dueBad && <p id={dueErrorId}>{t.dueIncomplete}</p>}
        {notice?.kind === "created" && <p role="status">{t.taskCreated}</p>}
        {notice?.kind === "failed" && (
          <WriteFailureRow
            failure={notice.failure}
            failedMessage={t.taskCreateFailed}
            labels={t}
            retrying={busy}
            onRetry={() => submit()}
          />
        )}
        <div className="work-actions">
          <button
            type="submit"
            disabled={busy}
            onClick={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            {t.createTask}
          </button>
          <button
            type="button"
            className="sk-btn sk-btn--quiet"
            disabled={busy}
            onClick={close}
          >
            {t.cancel}
          </button>
        </div>
      </form>
    </div>
  );
}
