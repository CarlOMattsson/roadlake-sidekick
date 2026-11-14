import { useEffect, useId, useRef, useState } from "react";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { DiscardAsk, keepVisible } from "../entry-write";
import { useUnsavedGuard } from "../../mcp-apps/unsaved-guard";
import { labelFor, type JournalLabels } from "../labels";
import type { JournalDraft, JournalDraftFields } from "../transport";
import {
  KEY_POINT_KINDS,
  KEY_POINT_MAX,
  KEY_POINTS_MAX,
  SUMMARY_MAX,
  TITLE_MAX,
  changedFields,
  follow,
  isKeyPointKind,
  valuesOf,
  type EditState,
  type EditValues,
} from "./edit-values";

/**
 * Title, summary and key points in one form, with Save and Cancel: the draft review's editor, and the entry's
 * (its edit mode). `fields` is whatever record holds them; a new object (a reload) moves the base and keeps the owner's edits.
 */
export function FieldsEditor({
  draft,
  busy,
  saveFailed,
  onSave,
  onCancel,
  confirmDiscard = false,
  labels: t,
}: {
  draft: Pick<JournalDraft, "title" | "summary" | "key_points">;
  busy: boolean;
  saveFailed: boolean;
  onSave: (changes: Partial<JournalDraftFields>) => void;
  onCancel: () => void;
  /** Cancel with unsaved changes asks first (the entry's editor); off, it closes at once (the draft's). */
  confirmDiscard?: boolean;
  labels: JournalLabels;
}) {
  const [state, setState] = useState<EditState>(() => {
    const initial = valuesOf(draft);
    return { values: initial, base: initial };
  });
  const [seen, setSeen] = useState(draft);
  const [problem, setProblem] = useState<"title" | "keyPoint">();
  const [asking, setAsking] = useState(false);
  useUnsavedGuard(Object.keys(changedFields(state)).length > 0);
  const titleInput = useRef<HTMLInputElement>(null);
  const pointInputs = useRef<(HTMLInputElement | null)[]>([]);
  const titleId = useId();
  const summaryId = useId();
  const errorId = useId();
  // A reload delivers a new draft: the base follows it and the owner's own edits are kept.
  if (draft !== seen) {
    setSeen(draft);
    setState((current) => follow(current, valuesOf(draft)));
  }
  useEffect(() => {
    titleInput.current?.focus();
  }, []);

  function setValues(update: (values: EditValues) => EditValues) {
    setProblem(undefined);
    setState((current) => ({ ...current, values: update(current.values) }));
  }
  // Runs from the button's click: the App iframe is sandboxed without allow-forms, so no form
  // submit event is ever dispatched.
  function submit() {
    if (busy) return;
    if (state.values.title.trim() === "") {
      setProblem("title");
      titleInput.current?.focus();
      return;
    }
    const emptyPoint = state.values.keyPoints.findIndex(
      (point) => point.text.trim() === "",
    );
    if (emptyPoint >= 0) {
      setProblem("keyPoint");
      pointInputs.current[emptyPoint]?.focus();
      return;
    }
    onSave(changedFields(state));
  }

  const { values } = state;
  return (
    <div
      className="journal-edit"
      role="group"
      aria-label={t.edit}
      onFocus={keepVisible}
    >
      <label htmlFor={titleId}>{t.titleLabel}</label>
      <input
        id={titleId}
        ref={titleInput}
        type="text"
        maxLength={TITLE_MAX}
        value={values.title}
        disabled={busy}
        aria-invalid={problem === "title" ? true : undefined}
        aria-describedby={problem === "title" ? errorId : undefined}
        onChange={(event) =>
          setValues((current) => ({ ...current, title: event.target.value }))
        }
      />
      {problem === "title" && (
        <p id={errorId} role="alert">
          {t.titleRequired}
        </p>
      )}
      <label htmlFor={summaryId}>{t.summaryLabel}</label>
      <textarea
        id={summaryId}
        maxLength={SUMMARY_MAX}
        value={values.summary}
        disabled={busy}
        onChange={(event) =>
          setValues((current) => ({
            ...current,
            summary: event.target.value,
          }))
        }
      />
      <h3>{t.keyPoints}</h3>
      {values.keyPoints.map((point, index) => (
        <div key={index} className="journal-keypoint">
          <select
            aria-label={t.keyPointKindFor(index + 1)}
            value={point.kind}
            disabled={busy}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                keyPoints: current.keyPoints.map((item, at) =>
                  at === index && isKeyPointKind(event.target.value)
                    ? { ...item, kind: event.target.value }
                    : item,
                ),
              }))
            }
          >
            {[
              ...KEY_POINT_KINDS,
              ...(isKeyPointKind(point.kind) ? [] : [point.kind]),
            ].map((kind) => (
              <option key={kind} value={kind}>
                {labelFor(t.keyPointKind, kind)}
              </option>
            ))}
          </select>
          <input
            type="text"
            maxLength={KEY_POINT_MAX}
            aria-label={t.keyPointText(index + 1)}
            ref={(element) => {
              pointInputs.current[index] = element;
            }}
            value={point.text}
            disabled={busy}
            aria-invalid={
              problem === "keyPoint" && point.text.trim() === ""
                ? true
                : undefined
            }
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                keyPoints: current.keyPoints.map((item, at) =>
                  at === index ? { ...item, text: event.target.value } : item,
                ),
              }))
            }
          />
          <button
            type="button"
            disabled={busy}
            aria-label={t.removeKeyPoint(index + 1)}
            onClick={() =>
              setValues((current) => ({
                ...current,
                keyPoints: current.keyPoints.filter((_, at) => at !== index),
              }))
            }
          >
            ×
          </button>
        </div>
      ))}
      {problem === "keyPoint" && <p role="alert">{t.keyPointRequired}</p>}
      <p>
        <button
          type="button"
          disabled={busy || values.keyPoints.length >= KEY_POINTS_MAX}
          onClick={() =>
            setValues((current) => ({
              ...current,
              keyPoints: [...current.keyPoints, { kind: "fact", text: "" }],
            }))
          }
        >
          {t.addKeyPoint}
        </button>
      </p>
      {saveFailed && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={t.saveFailed}
          retrying={busy}
          onRetry={submit}
        />
      )}
      {asking ? (
        <DiscardAsk
          labels={t}
          onDiscard={onCancel}
          onKeep={() => setAsking(false)}
        />
      ) : (
        <div className="journal-actions sk-form-actions">
          <button
            type="button"
            className="sk-btn--primary"
            disabled={busy}
            onClick={submit}
          >
            {t.save}
          </button>
          <button
            type="button"
            className="sk-btn--quiet"
            disabled={busy}
            onClick={() =>
              confirmDiscard && Object.keys(changedFields(state)).length > 0
                ? setAsking(true)
                : onCancel()
            }
          >
            {t.cancel}
          </button>
        </div>
      )}
    </div>
  );
}
