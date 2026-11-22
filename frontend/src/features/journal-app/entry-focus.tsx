import type {
  ChangeEvent,
  FocusEvent,
  KeyboardEvent,
  ReactNode,
  Ref,
} from "react";
import { KeyScope } from "../mcp-apps/ui/key-scope";
import { shortcutKeyParts } from "../mcp-apps/ui/shortcut-registry";
import "./entry.css";
import "./entry-read.css";

/**
 * The writing view of an entry, in pieces (from the desktop user test of the journal): the title
 * and the text as bare fields in the reading type, a quiet line under them, and a bar of Save and Cancel that rests
 * above the window's foot. The new entry, the text to add and the edit of an entry (entry-write.tsx, entry-edit.tsx)
 * are built from them, so the three look and answer the same keys: Ctrl or Cmd with Enter saves, Escape cancels.
 */

/** Words as the quiet line counts them: runs of text between white space. */
export function countWords(text: string): number {
  const words = text.trim();
  return words === "" ? 0 : words.split(/\s+/).length;
}

/** The key that saves, as it is written on the button ("Ctrl+Enter", "⌘+Enter" on a Mac). */
export function saveKeyName(): string {
  return shortcutKeyParts("Mod+Enter").join("+");
}

/**
 * The group around the fields. The keys come up from the fields inside (a shortcut map never fires in a field, so they
 * are handled here): Enter with Ctrl or Cmd runs `onSave`, Escape runs `onCancel`, which asks first when something is
 * unsaved.
 */
export function FocusForm({
  label,
  formRef,
  onSave,
  onCancel,
  onFocus,
  children,
}: {
  /** The group's accessible name, such as "New entry". */
  label: string;
  formRef?: Ref<HTMLDivElement>;
  onSave: () => void;
  onCancel: () => void;
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  children: ReactNode;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (
      event.key !== "Enter" ||
      !(event.ctrlKey || event.metaKey) ||
      event.nativeEvent.isComposing
    )
      return;
    event.preventDefault();
    onSave();
  }
  return (
    <KeyScope
      ref={formRef}
      className="journal-focus"
      role="group"
      aria-label={label}
      onFocus={onFocus}
      onKeyDown={onKeyDown}
      onEscape={onCancel}
    >
      {children}
    </KeyScope>
  );
}

/** A field's name that is read out but not drawn: the placeholder and the position say what it is to the eye. */
export function FocusLabel({
  htmlFor,
  text,
}: {
  htmlFor: string;
  text: string;
}) {
  return (
    <label className="journal-visually-hidden" htmlFor={htmlFor}>
      {text}
    </label>
  );
}

/** The title: one line in the display type with no frame. Enter moves on to the text instead of submitting. */
export function FocusTitle({
  id,
  label,
  placeholder,
  value,
  maxLength,
  disabled,
  invalid,
  describedBy,
  inputRef,
  onChange,
  onEnter,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  maxLength: number;
  disabled: boolean;
  invalid: boolean;
  describedBy?: string;
  inputRef: Ref<HTMLInputElement>;
  onChange: (value: string) => void;
  onEnter: () => void;
}) {
  return (
    <>
      <FocusLabel htmlFor={id} text={label} />
      <input
        id={id}
        ref={inputRef}
        className="journal-focus-title"
        type="text"
        maxLength={maxLength}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={describedBy}
        onChange={(event: ChangeEvent<HTMLInputElement>) =>
          onChange(event.target.value)
        }
        onKeyDown={(event) => {
          if (
            event.key !== "Enter" ||
            event.ctrlKey ||
            event.metaKey ||
            event.nativeEvent.isComposing
          )
            return;
          event.preventDefault();
          onEnter();
        }}
      />
    </>
  );
}

/** The text: a page that grows with what is written, in the reading type and width, so the lines break as they do when read. */
export function FocusText({
  id,
  label,
  placeholder,
  value,
  maxLength,
  disabled,
  invalid,
  describedBy,
  inputRef,
  onChange,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  maxLength: number;
  disabled: boolean;
  invalid: boolean;
  describedBy?: string;
  inputRef: Ref<HTMLTextAreaElement>;
  onChange: (value: string) => void;
}) {
  return (
    <>
      <FocusLabel htmlFor={id} text={label} />
      <textarea
        id={id}
        ref={inputRef}
        className="journal-focus-text"
        maxLength={maxLength}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={describedBy}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
          onChange(event.target.value)
        }
      />
    </>
  );
}

/** The quiet line under the fields ("Friday 20 November · 214 words"). */
export function FocusMeta({ children }: { children: ReactNode }) {
  return <p className="journal-focus-meta">{children}</p>;
}

/** Save and Cancel, resting above the foot; a tone and a shadow above it when text passes under it. */
export function FocusBar({ children }: { children: ReactNode }) {
  return <div className="journal-focus-bar">{children}</div>;
}
