import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { CloseIcon, PlusIcon } from "./icons";
import "./tokens.css";
import "./family.css";

/**
 * The create field (designsystem §2 and §3): + in a room head opens it under the rule, with focus.
 * Empty, its 48 px square is × and closes it. With text, the square is + (the primary) and creates. Enter creates
 * too, then empties the field and keeps the focus there, so several items can be typed in a row. Esc closes.
 * Labels arrive as props, so this file holds no text of its own. The caller returns the focus to its + in
 * onClose, because the field unmounts when it closes.
 *
 * onCreate may answer synchronously or with a promise. The text is emptied only when the answer
 * is not false and the promise does not reject. A failed write keeps the text, so it can be sent again. When
 * `errorLabel` is given, a failed write shows that line under the field (§3 *Fel vid skrivning*).
 */
export type CreateResult = boolean | void;

export type CreateFieldProps = {
  /** The field's accessible name. It is drawn for screen readers only. */
  label: string;
  /** The example shown while the field is empty, e.g. "Ny uppgift, t.ex. ring Anna". */
  placeholder: string;
  /**
   * Called with the trimmed text on Enter or +. Never called for an empty or blank field, and not again while an
   * earlier answer is pending. Return false, or a promise that resolves to false or rejects, when the write failed.
   */
  onCreate: (text: string) => CreateResult | Promise<CreateResult>;
  /** Called on × or Esc. */
  onClose: () => void;
  /** Accessible name of × while the field is empty, e.g. "Stäng". */
  closeLabel: string;
  /** Accessible name of + while the field has text, e.g. "Lägg till". */
  addLabel: string;
  /** The line under the field when a write fails, e.g. "Det gick inte att spara. Försök igen." Optional. */
  errorLabel?: string;
  /**
   * A muted line 4 px under the field, read out politely, e.g. "Tillagd: Ring Anna · Idag". The caller
   * sets it while the field is open and clears it when the field closes; nothing is drawn while it is empty.
   */
  note?: string;
  /** The text the field opens with (a name taken from a search, say). Read once, when the field mounts. */
  initialText?: string;
};

export function CreateField({
  label,
  placeholder,
  onCreate,
  onClose,
  closeLabel,
  addLabel,
  errorLabel,
  note,
  initialText = "",
}: CreateFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const inputRef = useRef<HTMLInputElement>(null);
  const pendingRef = useRef(false);
  const [text, setText] = useState(initialText);
  const [failed, setFailed] = useState(false);
  const trimmed = text.trim();
  const errorShown = failed && Boolean(errorLabel);

  // Opening the field puts the caret in it at once.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function settle(submitted: string, result: CreateResult) {
    pendingRef.current = false;
    if (result === false) {
      setFailed(true);
    } else {
      setFailed(false);
      // Empty only the text that was sent: the user may have typed on while the write was pending.
      setText((current) => (current.trim() === submitted ? "" : current));
    }
    inputRef.current?.focus();
  }

  function create() {
    if (trimmed === "" || pendingRef.current) return;
    const submitted = trimmed;
    setFailed(false);
    const outcome = onCreate(submitted);
    if (outcome instanceof Promise) {
      pendingRef.current = true;
      outcome.then(
        (value) => settle(submitted, value),
        () => settle(submitted, false),
      );
    } else {
      settle(submitted, outcome);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // Enter confirms an IME composition; it must not create the item.
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      create();
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  return (
    <>
      <div className="sk-createfield">
        <label className="sk-createfield__label" htmlFor={id}>
          {label}
        </label>
        <input
          id={id}
          ref={inputRef}
          className="sk-createfield__input"
          type="text"
          autoComplete="off"
          placeholder={placeholder}
          value={text}
          aria-describedby={errorShown ? errorId : undefined}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        {trimmed === "" ? (
          <button
            type="button"
            className="sk-createfield__btn"
            aria-label={closeLabel}
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        ) : (
          <button
            type="button"
            className="sk-createfield__btn sk-createfield__btn--add"
            aria-label={addLabel}
            onClick={create}
          >
            <PlusIcon />
          </button>
        )}
      </div>
      {note ? (
        <p aria-live="polite" className="sk-createfield__note">
          {note}
        </p>
      ) : null}
      {errorShown ? (
        <p id={errorId} role="alert" className="sk-error sk-error--row">
          {errorLabel}
        </p>
      ) : null}
    </>
  );
}
