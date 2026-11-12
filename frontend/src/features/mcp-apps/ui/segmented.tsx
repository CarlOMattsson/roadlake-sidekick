import { useRovingFocus } from "./roving-focus";
import "./segmented.css";

/**
 * A visible row of choices where exactly one option is pressed (`aria-pressed`). It replaces a
 * menu: every option is on screen, and nothing opens on top of the content. Arrow keys, Home and
 * End move focus only; Enter or Space (or a click) selects. Labels arrive as props, so the caller
 * picks the language and this file holds no text of its own.
 */
export type SegmentedOption<T extends string = string> = {
  value: T;
  label: string;
  /** Optional count shown on a second row under the label, e.g. "3". Accessible name: "Label 3". */
  badge?: string;
};

export type SegmentedProps<T extends string = string> = {
  /** Accessible name of the group, in the caller's language. */
  label: string;
  options: readonly SegmentedOption<T>[];
  /** The pressed option. `null` (or a value not in `options`) means none is pressed. */
  value: T | null;
  onChange: (value: T) => void;
  /** Disables every option, e.g. while a request is in flight. */
  disabled?: boolean;
};

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled = false,
}: SegmentedProps<T>) {
  const onKeyDown = useRovingFocus();

  // Roving tab stop: the pressed option is reachable with Tab. With nothing pressed, the first one is.
  const pressedIndex = options.findIndex((option) => option.value === value);
  const tabStopIndex = pressedIndex === -1 ? 0 : pressedIndex;

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- a container-level handler for the arrow/Home/End keys bubbling up from the focusable buttons inside it; the container itself is not a control.
    <div
      role="group"
      aria-label={label}
      className="sk-segmented"
      onKeyDown={onKeyDown}
    >
      {options.map((option, index) => {
        const pressed = index === pressedIndex;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={pressed}
            tabIndex={index === tabStopIndex ? 0 : -1}
            disabled={disabled}
            className={
              option.badge === undefined
                ? "sk-segmented__option"
                : "sk-segmented__option sk-segmented__option--badged"
            }
            onClick={() => {
              if (!pressed) onChange(option.value);
            }}
          >
            {option.badge === undefined ? (
              <span className="sk-segmented__label">{option.label}</span>
            ) : (
              <>
                <span className="sk-segmented__label">{option.label}</span>
                {/* This space is a whitespace text node between flex items, so it is not drawn,
                    but the accessible name becomes "Label 3". */}{" "}
                <span className="sk-segmented__badge">{option.badge}</span>
              </>
            )}
          </button>
        );
      })}
    </div>
  );
}
