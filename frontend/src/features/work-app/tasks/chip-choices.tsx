import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { KeyScope, onEscapeKey } from "../../mcp-apps/ui/key-scope";

export type ChipChoice = { value: string; label: string };

/**
 * A property chip that unfolds its choices (design system §3, egenskapschip): the repeat chip and the `priority` chip with
 * its value. A tap unfolds the choices as chips on a row of their own under the chips, the current one ticked
 * (aria-pressed), as the row menu's Status and Datum. Another choice runs `onChoose` and folds the chips away;
 * the current one only folds them and returns focus to the chip. Escape folds them and returns focus to the chip;
 * opening them puts focus on the ticked one, so Enter keeps it and Tab walks the others.
 */
export function ChipChoices({
  name,
  label,
  text,
  groupLabel,
  options,
  value,
  busy,
  onChoose,
}: {
  /** The chip's accessible name: the `changePriority` or `changeStatus` label, then the value. */
  name: string;
  /** The property row's name before the value (PropLabel); none draws the value alone. */
  label?: string;
  /** What the chip shows. */
  text: ReactNode;
  /** The name of the unfolded group: the `repeatPickerFor` label. */
  groupLabel: string;
  options: ChipChoice[];
  /** The ticked option. */
  value: string;
  busy: boolean;
  onChoose: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const chip = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open)
      panel.current
        ?.querySelector<HTMLElement>('[aria-pressed="true"]')
        ?.focus({ preventScroll: true });
  }, [open]);
  function close() {
    setOpen(false);
    chip.current?.focus();
  }
  function choose(next: string) {
    if (next === value) return close();
    setOpen(false);
    onChoose(next);
  }
  return (
    <>
      <button
        ref={chip}
        type="button"
        className="sk-chip work-prop-chip"
        aria-label={name}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        disabled={busy}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (open) onEscapeKey(event, close);
        }}
      >
        {label !== undefined && <PropLabel text={label} />}
        <span>{text}</span>
        <ChevronDownIcon size={16} />
      </button>
      {open && (
        <KeyScope
          ref={panel}
          id={panelId}
          role="group"
          aria-label={groupLabel}
          className="work-chip-choices"
          onEscape={close}
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className="sk-chip"
              aria-pressed={option.value === value}
              disabled={busy}
              onClick={() => choose(option.value)}
            >
              {option.label}
            </button>
          ))}
        </KeyScope>
      )}
    </>
  );
}

/**
 * The name of a property row of the Task detail ("Datum", "Upprepas"), muted, in a column of its own before the value,
 * so every row reads name · value and none needs a "Plats:" prefix. Hidden from assistive technology: the row's
 * accessible name already says what it changes.
 */
export function PropLabel({ text }: { text: string }) {
  return (
    <>
      <span className="work-prop-label" aria-hidden="true">
        {text}
      </span>
      {/* A space between name and value, so the visible text reads "Status Pågår" and the row's accessible name
          ("Ändra status: Pågår") holds it (axe label-content-name-mismatch; speech control finds the row by it). */}{" "}
    </>
  );
}
