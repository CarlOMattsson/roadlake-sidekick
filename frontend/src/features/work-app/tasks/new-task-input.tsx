import { useEffect, useId, useRef, useState } from "react";

import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { CreateField } from "../../mcp-apps/ui/create-field";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import {
  placeTitle,
  placeValue,
  useGroupChoices,
  type TaskPlace,
} from "../hierarchy/group-choices";
import { GroupSelect } from "../hierarchy/group-select";
import { groupSelectLabelsFor } from "../hierarchy/group-select-labels";
import type { WorkLabels } from "../shared/labels";
import type { NewTaskInputLabels } from "./new-task-input-labels";
import {
  writeFailure,
  type WorkTask,
  type WorkTaskCreate,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";
import "./new-task-input.css";
import { OpenChevron } from "./task-detail-controls";

/** The create_task fields that put a new Task in `place`: the one field it names, none for "no place". */
function placeFields(place: TaskPlace | null): Partial<WorkTaskCreate> {
  if (!place) return {};
  if (place.kind === "project") return { project_id: place.id };
  if (place.kind === "process") return { process_id: place.id };
  return { domain_id: place.id };
}

/**
 * The new-Task field of the fullscreen Work tabs (designsystem §3 "Skapa"): closed in rest, unfolded by + in the
 * tab row as the shared create field, 8 px under the row's rule, with focus. It creates a standalone Task with
 * create_task, with the typed title only: no due date, no Project, and no date is read out of the text. Enter and +
 * create and keep the field open with focus, so several Tasks can be typed in a row; Esc and × close it, and the
 * caller gives the focus back to its +. The failure and "added" lines stay mounted while the field is closed, so a
 * create that answers late is still told. A retry of the same title reuses one idempotency key, so a lost answer
 * never makes a second Task. The chosen place stays between two creates in a row.
 */
export function NewTaskInput({
  id,
  transport,
  labels: t,
  workLabels: wt,
  onCreated,
  open = false,
  onClose = () => {},
  showAdded = false,
  hidden = false,
  placeChoice = false,
}: {
  /** The id of the wrapper, which + names in aria-controls. */
  id?: string;
  transport: WorkTransport;
  labels: NewTaskInputLabels;
  /** The Work labels, for the shared write-failure texts and "Try again". */
  workLabels: WorkLabels;
  /** Called with the Task as stored; the caller shows it in its list. */
  onCreated: (task: WorkTask) => void;
  /** True shows the create field; the caller's + toggles it. */
  open?: boolean;
  /** × or Esc in the field. The caller closes it and puts the focus back on its +. */
  onClose?: () => void;
  /** True shows the "added" line under the field (Status, Projekt); false only announces it (the Agenda lists it). */
  showAdded?: boolean;
  /** Hides the field and its lines while a record is open over the list. */
  hidden?: boolean;
  /** True adds a "Place" row under the field (default: no place); false creates every Task in To sort. */
  placeChoice?: boolean;
}) {
  const [failure, setFailure] = useState<{
    title: string;
    place: TaskPlace | null;
    kind: WriteFailure;
  }>();
  const [added, setAdded] = useState<string>();
  const [place, setPlace] = useState<TaskPlace | null>(null);
  // The places are read when the field first opens with the row, not before.
  const choices = useGroupChoices(transport, placeChoice && open);
  const errorId = useId();
  const placeId = useId();
  const domains = choices.phase === "ready" ? choices.domains : [];
  // The key of each title whose delivery is not settled (it failed, or has no answer yet), by trimmed title: the same
  // title again (retry, or typed again) reuses its own key, also when another title was started in between.
  const pending = useRef(new Map<string, PendingKey>());
  // What the create field holds now, so a retry that succeeds empties it only if it still holds the retried title.
  const draft = useRef("");
  // The trimmed titles with a create in flight. A new field (after × or Esc) has no guard of its own.
  const inflight = useRef(new Set<string>());
  // Bumped when Retry succeeds and the field still holds that title: it then remounts empty.
  const [fieldKey, setFieldKey] = useState(0);
  useEffect(() => {
    // A field that opens or closes starts empty.
    draft.current = "";
  }, [open]);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function retry(title: string, at: TaskPlace | null) {
    void create(title, at).then((created) => {
      if (created && mounted.current && draft.current.trim() === title.trim()) {
        draft.current = "";
        setFieldKey((key) => key + 1);
      }
    });
  }

  /**
   * Resolves true when the Task was created, false when the write failed or the same title is already being
   * written. The create field empties only on true, so a failed title stays in the field.
   */
  function create(text: string, at: TaskPlace | null): Promise<boolean> {
    // The server checks the length: a title over the limit answers "invalid", named under the field.
    const clean = text.trim();
    if (!clean) return Promise.resolve(false);
    // The same title in another place is another Task, so the place is part of what a key stands for.
    const signature = `${placeValue(at)}\n${clean}`;
    // A title already in flight is not sent again: a second key for it would make a second Task.
    if (inflight.current.has(signature)) return Promise.resolve(false);
    inflight.current.add(signature);
    const attempt = keyFor(pending.current.get(signature), signature);
    pending.current.set(signature, attempt);
    setFailure(undefined);
    setAdded(undefined);
    return transport
      .createTask({ title: clean, ...placeFields(at) }, attempt.key)
      .then(({ task }) => {
        if (mounted.current) {
          if (pending.current.get(signature) === attempt)
            pending.current.delete(signature);
          setAdded(t.added(task.title, placeTitle(domains, at) ?? t.unsorted));
          onCreated(task);
        }
        return true;
      })
      .catch((error: unknown) => {
        if (mounted.current)
          setFailure({ title: clean, place: at, kind: writeFailure(error) });
        return false;
      })
      .finally(() => {
        inflight.current.delete(signature);
      });
  }

  const kind = failure?.kind;
  const failureText =
    kind === "failed"
      ? t.failed(failure!.title)
      : kind === "forbidden"
        ? wt.forbiddenWrite
        : kind === "invalid"
          ? wt.invalidChange
          : kind === "conflict"
            ? wt.createConflict
            : kind === "not_found"
              ? wt.notFound
              : undefined;

  return (
    <div
      id={id}
      className="work-new-task"
      hidden={hidden}
      onChange={(event) => {
        // The place picker's change bubbles here too; only the title field is the draft.
        if (event.target instanceof HTMLInputElement)
          draft.current = event.target.value;
      }}
    >
      {open ? (
        <CreateField
          key={fieldKey}
          label={t.field}
          placeholder={t.placeholder}
          closeLabel={t.close}
          addLabel={t.add}
          onCreate={(text) =>
            create(text, place).then((ok) => {
              // The field empties itself on success: the draft follows it.
              if (ok && draft.current.trim() === text.trim())
                draft.current = "";
              return ok;
            })
          }
          onClose={onClose}
        />
      ) : null}
      {placeChoice && open ? (
        <div className="work-new-task-place">
          <label htmlFor={placeId}>{t.place}</label>
          <GroupSelect
            id={placeId}
            label={t.place}
            value={place}
            choices={choices}
            labels={groupSelectLabelsFor(wt.dateLocale)}
            onChange={setPlace}
          />
        </div>
      ) : null}
      {failureText !== undefined && (
        <p id={errorId} role="alert" className="work-new-task-error">
          {failureText}
          {kind === "failed" && (
            <>
              {" "}
              <button
                type="button"
                className="work-new-task-retry"
                onClick={() => retry(failure!.title, failure!.place)}
              >
                {wt.retry}
              </button>
            </>
          )}
        </p>
      )}
      <p
        role="status"
        className={showAdded ? "work-new-task-added" : "work-visually-hidden"}
      >
        {added ?? ""}
      </p>
    </div>
  );
}

/**
 * The Agenda group of Tasks added with the row above, newest first. The Agenda lists dated work only,
 * so a new Task (no date) would not show there; this group shows it at once, in the agenda's own row
 * style. The filter text narrows it like the rest of the agenda. With `onOpen` a title opens the Task.
 */
export function RecentTasks({
  tasks,
  labels: t,
  statusLabel,
  query = "",
  onOpen,
  hidden = false,
}: {
  tasks: readonly WorkTask[];
  labels: NewTaskInputLabels;
  /** The status word for the glyph's accessible name, e.g. "Att göra". */
  statusLabel: (status: string) => string;
  query?: string;
  onOpen?: (task: WorkTask) => void;
  hidden?: boolean;
}) {
  const needle = query.trim().toLocaleLowerCase();
  const shown = needle
    ? tasks.filter((task) => task.title.toLocaleLowerCase().includes(needle))
    : tasks;
  if (shown.length === 0) return null;
  const heading = t.recentHeading(shown.length);
  return (
    <section
      className="work-new-task-recent"
      aria-label={heading}
      hidden={hidden}
    >
      <div className="work-agenda-group-head">
        <h3 className="work-agenda-group">{heading}</h3>
      </div>
      <ul className="work-list">
        {shown.map((task) => (
          <li key={task.id} className="work-agenda-row">
            <div className="work-agenda-line">
              <span className="work-agenda-glyph">
                <StatusGlyph
                  kind="task"
                  status={task.status}
                  label={statusLabel(task.status)}
                />
              </span>
              <div className="work-agenda-body">
                {onOpen ? (
                  <button type="button" onClick={() => onOpen(task)}>
                    {task.title}
                  </button>
                ) : (
                  <p className="work-card-title">{task.title}</p>
                )}
                <p className="work-card-meta">
                  <span>{t.undated}</span>
                </p>
              </div>
              {onOpen && <OpenChevron />}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
