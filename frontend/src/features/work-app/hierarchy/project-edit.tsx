import { useEffect, useId, useRef, useState } from "react";
import { projectStatusLabel, type WorkLabels } from "../shared/labels";
import {
  isCompleteDate,
  keepEdits,
  titleProblem,
  type TitleProblem,
} from "../shared/fields";
import {
  PROJECT_STATUSES,
  type ProjectStatusValue,
  type WorkProject,
  type WorkProjectChanges,
} from "../transport/transport";
import { useUnsavedGuard } from "../../mcp-apps/unsaved-guard";

/** Description limit of the update_project schema (10,000 characters). */
export const DESCRIPTION_MAX_LENGTH = 10_000;

/**
 * Editable Project fields as the form shows them. Dates are calendar dates (YYYY-MM-DD) or "";
 * they go to the server unchanged, so no time zone conversion can move them to another day.
 */
export type ProjectDraft = {
  title: string;
  status: string;
  description: string;
  startDate: string;
  targetDate: string;
};
type DraftField = keyof ProjectDraft;
type DateField = "startDate" | "targetDate";
/**
 * `base` is the Project as the user last saw it (opening the editor, or the latest reload). A field
 * counts as changed only while it differs from base, so an edit reverted by hand is not sent.
 * `dateIncomplete` is set per date while its input holds a partial entry the browser cannot read.
 */
export type ProjectDraftState = {
  values: ProjectDraft;
  base: ProjectDraft;
  dateIncomplete: Record<DateField, boolean>;
};
export type ProjectFieldProblem =
  | TitleProblem
  | "descriptionTooLong"
  | "startIncomplete"
  | "targetIncomplete";

export function draftFromProject(project: WorkProject): ProjectDraft {
  return {
    title: project.title,
    status: project.status,
    description: project.description ?? "",
    startDate: project.start_date ?? "",
    targetDate: project.target_date ?? "",
  };
}

/** The first field problem that blocks Save, or none. */
export function projectFieldProblem(
  state: ProjectDraftState,
): ProjectFieldProblem | undefined {
  const title = titleProblem(state.values.title);
  if (title) return title;
  if (Array.from(state.values.description).length > DESCRIPTION_MAX_LENGTH)
    return "descriptionTooLong";
  const { values, dateIncomplete } = state;
  if (
    dateIncomplete.startDate ||
    (values.startDate !== "" && !isCompleteDate(values.startDate))
  )
    return "startIncomplete";
  if (
    dateIncomplete.targetDate ||
    (values.targetDate !== "" && !isCompleteDate(values.targetDate))
  )
    return "targetIncomplete";
  return undefined;
}

/**
 * Only the fields that differ from what the user last saw. Title and description are trimmed the
 * way the form saves them; an empty description or date is sent as null, which clears it. An
 * incomplete date is not a change; Save is blocked for it instead.
 */
export function changedProjectFields(
  state: ProjectDraftState,
): WorkProjectChanges {
  const { values, base, dateIncomplete } = state;
  const changes: WorkProjectChanges = {};
  if (values.title.trim() !== base.title.trim())
    changes.title = values.title.trim();
  if (values.status !== base.status)
    changes.status = values.status as ProjectStatusValue;
  if (values.description.trim() !== base.description.trim())
    changes.description = values.description.trim() || null;
  if (!dateIncomplete.startDate && values.startDate !== base.startDate)
    changes.start_date = values.startDate || null;
  if (!dateIncomplete.targetDate && values.targetDate !== base.targetDate)
    changes.target_date = values.targetDate || null;
  return changes;
}

export function ProjectEditor({
  project,
  busy,
  saveFailed,
  onSave,
  onCancel,
  labels: t,
}: {
  project: WorkProject;
  busy: boolean;
  saveFailed: boolean;
  onSave: (changes: WorkProjectChanges) => void;
  onCancel: () => void;
  labels: WorkLabels;
}) {
  const [state, setState] = useState<ProjectDraftState>(() => {
    const initial = draftFromProject(project);
    return {
      values: initial,
      base: initial,
      dateIncomplete: { startDate: false, targetDate: false },
    };
  });
  const [seenProject, setSeenProject] = useState(project);
  const [problem, setProblem] = useState<ProjectFieldProblem>();
  useUnsavedGuard(Object.keys(changedProjectFields(state)).length > 0);
  const titleInput = useRef<HTMLInputElement>(null);
  const descriptionInput = useRef<HTMLTextAreaElement>(null);
  const startInput = useRef<HTMLInputElement>(null);
  const targetInput = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const statusId = useId();
  const descriptionId = useId();
  const startId = useId();
  const targetId = useId();
  const titleErrorId = useId();
  const descriptionErrorId = useId();
  const startErrorId = useId();
  const targetErrorId = useId();
  // Adjusts state during render when a reload delivers a new Project (same pattern as TaskEditor).
  if (project !== seenProject) {
    setSeenProject(project);
    const fresh = draftFromProject(project);
    setState((current) => ({
      values: keepEdits(current, fresh),
      base: fresh,
      dateIncomplete: current.dateIncomplete,
    }));
  }
  useEffect(() => {
    titleInput.current?.focus();
  }, []);
  const statuses: string[] = (PROJECT_STATUSES as readonly string[]).includes(
    state.values.status,
  )
    ? [...PROJECT_STATUSES]
    : [...PROJECT_STATUSES, state.values.status];
  const titleBad = problem === "required" || problem === "tooLong";
  const descriptionBad = problem === "descriptionTooLong";
  const startBad = problem === "startIncomplete";
  const targetBad = problem === "targetIncomplete";

  function setField(field: DraftField, value: string) {
    setProblem(undefined);
    setState((current) => ({
      ...current,
      values: { ...current.values, [field]: value },
    }));
  }
  function setDate(field: DateField, value: string, incomplete: boolean) {
    setProblem(undefined);
    setState((current) => ({
      ...current,
      values: { ...current.values, [field]: value },
      dateIncomplete: { ...current.dateIncomplete, [field]: incomplete },
    }));
  }
  // Save runs from the button's click, not the form's submit event: the App iframe is sandboxed
  // without allow-forms, where the browser never dispatches submit. Enter still clicks the button.
  function submit() {
    if (busy) return;
    const found = projectFieldProblem(state);
    setProblem(found);
    if (found === "startIncomplete") {
      startInput.current?.focus();
      return;
    }
    if (found === "targetIncomplete") {
      targetInput.current?.focus();
      return;
    }
    if (found === "descriptionTooLong") {
      descriptionInput.current?.focus();
      return;
    }
    if (found) {
      titleInput.current?.focus();
      return;
    }
    onSave(changedProjectFields(state));
  }

  return (
    <form className="work-edit" aria-label={t.edit} noValidate>
      <label htmlFor={titleId}>{t.titleLabel}</label>
      <input
        id={titleId}
        ref={titleInput}
        type="text"
        value={state.values.title}
        disabled={busy}
        aria-invalid={titleBad ? true : undefined}
        aria-describedby={titleBad ? titleErrorId : undefined}
        onChange={(event) => setField("title", event.target.value)}
      />
      {titleBad && (
        <p id={titleErrorId}>
          {problem === "required" ? t.titleRequired : t.titleTooLong}
        </p>
      )}
      <label htmlFor={statusId}>{t.status}</label>
      <select
        id={statusId}
        value={state.values.status}
        disabled={busy}
        onChange={(event) => setField("status", event.target.value)}
      >
        {statuses.map((value) => (
          <option key={value} value={value}>
            {projectStatusLabel(t, value)}
          </option>
        ))}
      </select>
      <label htmlFor={descriptionId}>{t.description}</label>
      <textarea
        id={descriptionId}
        ref={descriptionInput}
        rows={4}
        value={state.values.description}
        disabled={busy}
        aria-invalid={descriptionBad ? true : undefined}
        aria-describedby={descriptionBad ? descriptionErrorId : undefined}
        onChange={(event) => setField("description", event.target.value)}
      />
      {descriptionBad && <p id={descriptionErrorId}>{t.descriptionTooLong}</p>}
      <label htmlFor={startId}>{t.startDate}</label>
      <div className="work-due-row">
        <input
          id={startId}
          ref={startInput}
          type="date"
          value={state.values.startDate}
          disabled={busy}
          aria-invalid={startBad ? true : undefined}
          aria-describedby={startBad ? startErrorId : undefined}
          onChange={(event) =>
            setDate(
              "startDate",
              event.target.value,
              event.target.validity.badInput,
            )
          }
        />
        {state.values.startDate && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setDate("startDate", "", false)}
          >
            {t.clearStartDate}
          </button>
        )}
      </div>
      {startBad && <p id={startErrorId}>{t.dateIncomplete}</p>}
      <label htmlFor={targetId}>{t.targetDate}</label>
      <div className="work-due-row">
        <input
          id={targetId}
          ref={targetInput}
          type="date"
          value={state.values.targetDate}
          disabled={busy}
          aria-invalid={targetBad ? true : undefined}
          aria-describedby={targetBad ? targetErrorId : undefined}
          onChange={(event) =>
            setDate(
              "targetDate",
              event.target.value,
              event.target.validity.badInput,
            )
          }
        />
        {state.values.targetDate && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setDate("targetDate", "", false)}
          >
            {t.clearTargetDate}
          </button>
        )}
      </div>
      {targetBad && <p id={targetErrorId}>{t.dateIncomplete}</p>}
      {saveFailed && (
        <p role="alert">
          {t.saveFailed}{" "}
          <button type="button" disabled={busy} onClick={() => submit()}>
            {t.retry}
          </button>
        </p>
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
          {t.save}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
    </form>
  );
}
