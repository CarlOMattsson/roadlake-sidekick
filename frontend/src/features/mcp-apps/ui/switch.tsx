import "./switch.css";

/**
 * The one on/off control (helhet rule 8, designsystem §3 Kontroll): a ruled track, on = a track in the text colour
 * with the knob in the page colour at the end, off = a 2 px edge in --sk-border with a muted knob at the start. No
 * green and no word beside it: the knob's place and the filled track carry the state without colour, and the row's
 * meta line names it ("På · 214 anteckningar"). Use it for a setting that takes effect at once (a memory source, "Visa
 * arkiverade"); a choice between named values is `Segmented`, and a view is `Tabs`. The button is 48 wide and 40 high
 * around the 44 × 24 track, and 48 × 48 to tap. `role="switch"` with `aria-checked`; `label` names the setting.
 */
export type SwitchProps = {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** The setting's name for assistive technology, in the caller's language. */
  label: string;
  disabled?: boolean;
  className?: string;
};

export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
  className,
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={className ? `sk-switch ${className}` : "sk-switch"}
      data-on={checked ? "true" : "false"}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="sk-switch__track" aria-hidden="true">
        <span className="sk-switch__knob" />
      </span>
    </button>
  );
}
