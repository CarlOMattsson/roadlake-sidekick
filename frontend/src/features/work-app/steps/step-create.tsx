import { useEffect, useRef, useState } from "react";
import { type WorkLabels } from "../shared/labels";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { titleProblem } from "../shared/fields";
import { useSingleFlight } from "../shared/use-single-flight";
import { CreateField } from "../../mcp-apps/ui/create-field";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import {
  writeFailure,
  type WorkStep,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";
import "../tasks/new-task-input.css";

/** What the Step create field last answered with, shown under it: a write failure or a title over the limit. */
type StepCreateFailure = { title: string; kind: WriteFailure | "tooLong" };

/**
 * Appends a Step to the Task with create_task_step, through the shared create field (the same one the new Task
 * and the new contact use). Enter and + create and keep the focus in the field, so several Steps can be typed in
 * a row; × and Esc close it and give the focus back to `addStep`. Submitting the same title again reuses
 * one key, so a retry after a lost response replays the created Step instead of adding a second one.
 */
export function StepCreate({
  taskId,
  transport,
  labels: t,
  onWriteStart,
  onCreated,
}: {
  taskId: string;
  transport: WorkTransport;
  labels: WorkLabels;
  onWriteStart: () => void;
  onCreated: (step: WorkStep) => void;
}) {
  const [failure, setFailure] = useState<StepCreateFailure>();
  // Closed, the section shows one quiet `addStep` line; opening it puts the focus in the field.
  const [open, setOpen] = useState(false);
  // Bumped when Retry succeeds and the field still holds that title: it then remounts empty.
  const [fieldKey, setFieldKey] = useState(0);
  const opener = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  // What the field holds now, so a retry that succeeds empties it only if it still holds the retried title.
  const draft = useRef("");
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
    // The opener is mounted again after the field closes; the focus goes back to it.
    if (!open && returnFocus.current) {
      returnFocus.current = false;
      opener.current?.focus();
    }
  }, [open]);

  /** Closes the field and drops what was typed in it; a write already running still finishes. */
  function close() {
    returnFocus.current = true;
    draft.current = "";
    setFailure(undefined);
    setOpen(false);
  }

  /** Resolves true when the Step was created, so the field empties; false keeps the text. */
  function create(text: string): Promise<boolean> {
    const cleanTitle = text.trim();
    if (flight.isRunning() || !cleanTitle) return Promise.resolve(false);
    if (titleProblem(cleanTitle)) {
      setFailure({ title: cleanTitle, kind: "tooLong" });
      return Promise.resolve(false);
    }
    const pendingKey = keyFor(
      pendingWrite.current,
      JSON.stringify([cleanTitle]),
    );
    pendingWrite.current = pendingKey;
    flight.enter();
    setFailure(undefined);
    onWriteStart();
    return transport
      .createTaskStep(taskId, cleanTitle, pendingKey.key)
      .then((result) => {
        pendingWrite.current = undefined;
        if (mounted.current) onCreated(result.step);
        return true;
      })
      .catch((error: unknown) => {
        if (mounted.current)
          setFailure({ title: cleanTitle, kind: writeFailure(error) });
        return false;
      })
      .finally(() => {
        flight.leave();
      });
  }

  function retry(title: string) {
    void create(title).then((created) => {
      if (created && mounted.current && draft.current.trim() === title) {
        draft.current = "";
        setFieldKey((key) => key + 1);
      }
    });
  }

  if (!open)
    return (
      <div>
        <button
          ref={opener}
          type="button"
          className="work-add-row sk-action-row"
          onClick={() => setOpen(true)}
        >
          <PlusIcon />
          {t.addStep}
        </button>
      </div>
    );
  const kind = failure?.kind;
  const failureText =
    kind === "tooLong"
      ? t.titleTooLong
      : kind === "conflict"
        ? t.createConflict
        : kind === "forbidden"
          ? t.forbiddenWrite
          : kind === "invalid"
            ? t.invalidChange
            : kind === "not_found"
              ? t.notFound
              : kind === "failed"
                ? t.stepCreateFailed
                : undefined;
  return (
    <div
      className="work-new-task"
      onInput={(event) => {
        draft.current = (event.target as HTMLInputElement).value;
        // A title over the limit is told until it is edited. `input` bubbles on Preact too, where onChange does not.
        setFailure((now) => (now?.kind === "tooLong" ? undefined : now));
      }}
    >
      <CreateField
        key={fieldKey}
        label={t.stepTitle}
        placeholder={t.stepPlaceholder}
        closeLabel={t.closeStepField}
        addLabel={t.addStep}
        onCreate={(text) =>
          create(text).then((ok) => {
            // The field empties itself on success: the draft follows it.
            if (ok && draft.current.trim() === text.trim()) draft.current = "";
            return ok;
          })
        }
        onClose={close}
      />
      {failureText !== undefined && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={failureText}
          onRetry={kind === "failed" ? () => retry(failure!.title) : undefined}
        />
      )}
    </div>
  );
}
