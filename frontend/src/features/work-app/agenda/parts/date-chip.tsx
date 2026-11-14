import { useRef } from "react";
import { isCompleteDate } from "../../shared/fields";
import { editsDate } from "./agenda-helpers";

/**
 * `rescheduleChoose` is the date control itself: the chip as drawn, with the platform's date input laid
 * invisibly over its 48 target, so a tap opens the platform's own picker and no native field (its "dd/mm/yyyy", its
 * blue ring) is ever shown. The input holds the Task's date, so the picker opens on it. A write is only for an
 * intended choice: the picker's own `change` writes at once, but a date edited from the keys (a
 * digit, an arrow, Backspace) is held until Enter or blur and written then, only if it is a complete date other than
 * the Task's own, so a half-typed "2030-01-1" or an arrow per press never writes. Enter with nothing held, and Space,
 * ask for the picker (`showPicker`, which a cross-origin host frame may refuse; typing still works there); a click does
 * too, where the platform has no picker indicator to fill the field. The field always goes back to the Task's date
 * after a choice, so a write that is held back or fails leaves no unsaved date in it.
 */
export function DateChip({
  text,
  label,
  value,
  disabled,
  onPick,
}: {
  text: string;
  label: string;
  value: string;
  disabled: boolean;
  onPick: (day: string) => void;
}) {
  // True while the keys have edited the field and no Enter or blur has settled it.
  const edited = useRef(false);
  function openPicker(input: HTMLInputElement): boolean {
    try {
      input.showPicker();
      return true;
    } catch {
      // Refused (a cross-origin frame, or no picker): the keys type the date instead.
      return false;
    }
  }
  /** Writes the field's date if it is a complete one other than the Task's; the field then shows the Task's date again. */
  function settle(input: HTMLInputElement) {
    edited.current = false;
    const picked = input.value;
    // Reset first: the write may be held back or fail, and a new date from outside remounts the field (key).
    input.value = value;
    if (picked !== value && isCompleteDate(picked)) onPick(picked);
  }
  return (
    <span
      className="sk-chip work-agenda-date-chip"
      data-disabled={disabled || undefined}
    >
      <span aria-hidden="true">{text}</span>
      <input
        // A new date from outside resets what was typed.
        key={value}
        type="date"
        className="work-agenda-date-input"
        aria-label={label}
        defaultValue={value}
        disabled={disabled}
        onKeyDown={(event) => {
          const input = event.currentTarget;
          if (editsDate(event.key)) {
            edited.current = true;
            return;
          }
          if (event.key === "Enter" && edited.current) {
            event.preventDefault();
            settle(input);
            return;
          }
          if (event.key !== "Enter" && event.key !== " ") return;
          if (openPicker(input)) event.preventDefault();
        }}
        onClick={(event) => {
          // A pointer picks from the picker: its change writes at once.
          edited.current = false;
          openPicker(event.currentTarget);
        }}
        onBlur={(event) => settle(event.currentTarget)}
        onChange={(event) => {
          if (edited.current) return;
          settle(event.currentTarget);
        }}
      />
    </span>
  );
}
