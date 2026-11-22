import { useEffect, useId, useRef, useState } from "react";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { useUnsavedGuard } from "../mcp-apps/unsaved-guard";
import { formatDayHeading } from "./dates";
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
} from "./draft-review-parts/edit-values";
import {
  countWords,
  FocusBar,
  FocusForm,
  FocusMeta,
  FocusText,
  FocusTitle,
  saveKeyName,
} from "./entry-focus";
import { DiscardAsk, keepVisible } from "./entry-write";
import { labelFor, type JournalLabels } from "./labels";
import type { JournalDraft, JournalDraftFields } from "./transport";
import "./entry.css";
import "./entry-read.css";

/**
 * The edit of an entry as a focus view (entry-focus.tsx): the title and the text in the reading type, bare, with the
 * key points under them. The title stands once, as the field (the view's own heading is hidden while this is open).
 * `draft` is the record that holds the fields; a new object (a reload) moves the base and keeps the owner's edits.
 * Ctrl or Cmd with Enter saves, Escape cancels and asks first when something is changed.
 */
export function EntryEditForm({
  draft,
  date,
  summaryByOwner,
  busy,
  saveFailed,
  onSave,
  onCancel,
  labels: t,
}: {
  draft: Pick<JournalDraft, "title" | "summary" | "key_points">;
  /** The entry's day (YYYY-MM-DD), for the quiet line. */
  date: string;
  /** The text holds the owner's own words: its field is named "Your text", not "Summary". */
  summaryByOwner: boolean;
  busy: boolean;
  saveFailed: boolean;
  onSave: (changes: Partial<JournalDraftFields>) => void;
  onCancel: () => void;
  labels: JournalLabels;
}) {
  const [state, setState] = useState<EditState>(() => {
    const initial = valuesOf(draft);
    return { values: initial, base: initial };
  });
  const [seen, setSeen] = useState(draft);
  const [problem, setProblem] = useState<"title" | "keyPoint">();
  const [asking, setAsking] = useState(false);
  const changed = Object.keys(changedFields(state)).length > 0;
  useUnsavedGuard(changed);
  const titleInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLTextAreaElement>(null);
  const pointInputs = useRef<(HTMLInputElement | null)[]>([]);
  const titleId = useId();
  const textId = useId();
  const errorId = useId();
  // A reload delivers a new record: the base follows it and the owner's own edits are kept.
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
  // Runs from the button's click or the key: the App iframe is sandboxed without allow-forms.
  function save() {
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
  /** Escape asks only when something is changed; a second Escape while it asks keeps editing. */
  function cancel() {
    if (asking) setAsking(false);
    else if (changed) setAsking(true);
    else onCancel();
  }

  const { values } = state;
  const saveKey = saveKeyName();
  return (
    <FocusForm
      label={t.edit}
      onSave={save}
      onCancel={cancel}
      onFocus={keepVisible}
    >
      <FocusTitle
        id={titleId}
        label={t.titleLabel}
        placeholder={t.titlePlaceholder}
        value={values.title}
        maxLength={TITLE_MAX}
        disabled={busy}
        invalid={problem === "title"}
        describedBy={problem === "title" ? errorId : undefined}
        inputRef={titleInput}
        onChange={(title) => setValues((current) => ({ ...current, title }))}
        onEnter={() => textInput.current?.focus()}
      />
      {problem === "title" && (
        <p id={errorId} role="alert">
          {t.titleRequired}
        </p>
      )}
      <FocusText
        id={textId}
        label={summaryByOwner ? t.entryTextLabel : t.summaryLabel}
        placeholder={t.textPlaceholder}
        value={values.summary}
        maxLength={SUMMARY_MAX}
        disabled={busy}
        invalid={false}
        inputRef={textInput}
        onChange={(summary) =>
          setValues((current) => ({ ...current, summary }))
        }
      />
      <FocusMeta>
        {t.writeMeta(
          formatDayHeading(date, t.dateLocale, ownerToday()),
          countWords(values.summary),
        )}
      </FocusMeta>
      <div className="journal-edit journal-focus-points">
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
      </div>
      {saveFailed && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={t.saveFailed}
          retrying={busy}
          onRetry={save}
        />
      )}
      <FocusBar>
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
              aria-keyshortcuts="Control+Enter Meta+Enter"
              title={`${t.save} (${saveKey})`}
              onClick={save}
            >
              {t.save}
            </button>
            <button
              type="button"
              className="sk-btn--quiet"
              disabled={busy}
              aria-keyshortcuts="Escape"
              onClick={cancel}
            >
              {t.cancel}
            </button>
          </div>
        )}
      </FocusBar>
    </FocusForm>
  );
}
