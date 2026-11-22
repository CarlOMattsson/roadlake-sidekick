import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type RefObject,
} from "react";
import { ownerToday } from "../mcp-apps/app-timezone";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { useUnsavedGuard } from "../mcp-apps/unsaved-guard";
import { calendarDate, formatDayHeading } from "./dates";
import {
  countWords,
  FocusBar,
  FocusForm,
  FocusMeta,
  FocusText,
  FocusTitle,
  saveKeyName,
} from "./entry-focus";
import { entryFitsBody, TEXT_MAX, TITLE_MAX } from "./entry-limits";
import type { JournalLabels } from "./labels";
import { writeFailure, type WriteFailure } from "./transport";
import "./journal.css";
import "./entry.css";

/**
 * Keeps the focused field in view when the on-screen keyboard opens (phones): the browser scrolls the field into
 * view on its own in most hosts, this covers the ones that do not. Absent in a test DOM, so optional.
 */
export function keepVisible(event: FocusEvent<HTMLElement>) {
  const target = event.target;
  target.scrollIntoView?.({ block: "nearest" });
}

/**
 * The on-screen keyboard opens after the focus event and resizes the window (Capacitor's SystemBars pads the WebView by
 * the keyboard height; hosts with `interactive-widget=resizes-content` shrink the visual viewport). Each resize while a
 * field of `form` has focus brings that field back into view, so the keyboard never covers what is being typed.
 */
export function useKeepFocusedFieldVisible(
  form: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const viewport = window.visualViewport;
    function onResize() {
      const active = document.activeElement;
      if (active instanceof HTMLElement && form.current?.contains(active))
        active.scrollIntoView?.({ block: "nearest" });
    }
    window.addEventListener("resize", onResize);
    viewport?.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      viewport?.removeEventListener("resize", onResize);
    };
  }, [form]);
}

/** "Discard what you wrote? [Discard] [Keep writing]": asked only when there is something unsaved to lose. */
export function DiscardAsk({
  labels: t,
  onDiscard,
  onKeep,
}: {
  labels: JournalLabels;
  onDiscard: () => void;
  onKeep: () => void;
}) {
  return (
    <div className="journal-undo" role="group">
      <p role="status">{t.discardAsk}</p>
      <div className="journal-actions">
        <button type="button" className="sk-btn--primary" onClick={onDiscard}>
          {t.discardYes}
        </button>
        <button type="button" className="sk-btn--quiet" onClick={onKeep}>
          {t.keepWriting}
        </button>
      </div>
    </div>
  );
}

type Problem = "title" | "text" | "tooLong";
type Failure = WriteFailure;

/**
 * The owner's own words as a focus view (entry-focus.tsx): a new entry (title and text) or text added to an entry
 * (text only). It keeps what was typed through every failure and says so calmly. `submit` writes with the idempotency
 * key of this attempt; the key is the same on a retry of the same values and a new one as soon as the values or
 * `signatureBase` (the target and version) differ. The form is closed by the parent after a successful write.
 * Ctrl or Cmd with Enter saves; Escape cancels, and asks first only when something is written.
 */
export function EntryTextForm({
  labels: t,
  kind,
  note,
  date,
  signatureBase,
  submit,
  onCancel,
  onConflict,
}: {
  labels: JournalLabels;
  kind: "new" | "append";
  /** What the quiet line names when the entry's day is not known: the line the form used to show under its heading. */
  note?: string;
  /** The day (YYYY-MM-DD) the text belongs to; a new entry's `signatureBase` is it too, so it is read from there. */
  date?: string;
  /** Names what the write targets (day, or entry and version), so a changed target gets a new key. */
  signatureBase: string;
  submit: (
    values: { title: string; text: string },
    idempotencyKey: string,
  ) => Promise<void>;
  onCancel: () => void;
  /** A stale version: the parent reads the entry again, and the text stays in the form. */
  onConflict?: () => void;
}) {
  const isNew = kind === "new";
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<Problem>();
  const [failure, setFailure] = useState<Failure>();
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  useUnsavedGuard(title.trim() !== "" || text.trim() !== "");
  const pendingKey = useRef<PendingKey | undefined>(undefined);
  const titleInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const textId = useId();
  const errorId = useId();
  const heading = isNew ? t.newEntryHeading : t.appendText;
  useKeepFocusedFieldVisible(formRef);

  // Focus moves into the form the user just opened, without the browser's own scroll: a new entry opens with the day
  // heading and the form in view (scrolled to the top, no jump to a half-open keyboard); an appended text is
  // brought into view where it is.
  useEffect(() => {
    (isNew ? titleInput : textInput).current?.focus({ preventScroll: true });
    if (isNew) {
      const root = document.scrollingElement;
      if (root) root.scrollTop = 0;
    } else formRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [isNew]);

  // Runs from the button's click or the key: the App iframe is sandboxed without allow-forms, so no submit event is
  // dispatched.
  function save() {
    if (busy) return;
    if (isNew && title.trim() === "") {
      setProblem("title");
      titleInput.current?.focus();
      return;
    }
    if (text.trim() === "") {
      setProblem("text");
      textInput.current?.focus();
      return;
    }
    const values = { title: title.trim(), text };
    if (!entryFitsBody(values.title, values.text)) {
      setProblem("tooLong");
      textInput.current?.focus();
      return;
    }
    const pending = keyFor(
      pendingKey.current,
      JSON.stringify([kind, signatureBase, values.title, values.text]),
    );
    pendingKey.current = pending;
    setBusy(true);
    setFailure(undefined);
    submit(values, pending.key)
      .then(() => {
        pendingKey.current = undefined;
      })
      .catch((error: unknown) => {
        const how = writeFailure(error);
        setFailure(how);
        if (how === "conflict") onConflict?.();
      })
      .finally(() => setBusy(false));
  }

  /** Escape asks only when something is written; a second Escape while it asks keeps writing. */
  function cancel() {
    if (asking) setAsking(false);
    else if (title.trim() !== "" || text.trim() !== "") setAsking(true);
    else onCancel();
  }

  const failureText =
    failure === "conflict"
      ? t.entryEditConflict
      : failure === "invalid"
        ? t.entryInvalid
        : failure === "forbidden"
          ? t.forbiddenWrite
          : failure
            ? isNew
              ? t.entryCreateFailed
              : t.appendTextFailed
            : undefined;

  const day = date ?? (calendarDate.test(signatureBase) ? signatureBase : "");
  const dayText = day
    ? formatDayHeading(day, t.dateLocale, ownerToday())
    : note;
  const saveName = isNew ? t.save : t.appendTextSave;

  return (
    <FocusForm
      formRef={formRef}
      label={heading}
      onSave={save}
      onCancel={cancel}
      onFocus={keepVisible}
    >
      <h3 className="journal-visually-hidden">{heading}</h3>
      {isNew && (
        <>
          <FocusTitle
            id={titleId}
            label={t.titleLabel}
            placeholder={t.titlePlaceholder}
            value={title}
            maxLength={TITLE_MAX}
            disabled={busy}
            invalid={problem === "title"}
            describedBy={problem === "title" ? errorId : undefined}
            inputRef={titleInput}
            onChange={(value) => {
              setProblem(undefined);
              setTitle(value);
            }}
            onEnter={() => textInput.current?.focus()}
          />
          {problem === "title" && (
            <p id={errorId} role="alert">
              {t.titleRequired}
            </p>
          )}
        </>
      )}
      <FocusText
        id={textId}
        label={isNew ? t.entryTextLabel : t.appendTextLabel}
        placeholder={isNew ? t.textPlaceholder : t.appendPlaceholder}
        value={text}
        maxLength={TEXT_MAX}
        disabled={busy}
        invalid={problem === "text" || problem === "tooLong"}
        describedBy={
          problem === "text" || problem === "tooLong" ? errorId : undefined
        }
        inputRef={textInput}
        onChange={(value) => {
          setProblem(undefined);
          setText(value);
        }}
      />
      {problem === "text" && (
        <p id={errorId} role="alert">
          {isNew ? t.entryTextRequired : t.appendTextRequired}
        </p>
      )}
      {problem === "tooLong" && (
        <p id={errorId} role="alert">
          {t.entryTooLong}
        </p>
      )}
      <FocusMeta>{t.writeMeta(dayText, countWords(text))}</FocusMeta>
      {!isNew && <p className="journal-muted">{t.appendTextNote}</p>}
      {failureText && (
        <ErrorNotice
          placement="row"
          locale={t.dateLocale}
          message={failureText}
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
              aria-busy={busy || undefined}
              aria-keyshortcuts="Control+Enter Meta+Enter"
              title={`${saveName} (${saveKeyName()})`}
              onClick={save}
            >
              {saveName}
            </button>
            {/* Avbryt is the quiet text button beside Save, as in every form of the family. */}
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
