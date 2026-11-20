import type { Ref } from "react";

import { KeyScope } from "./key-scope";
import "./tabs.css";

/**
 * Level 2 navigation (designsystem §3 Flikar, helhet rule 3): the views of one room, as underlined text tabs. Level 1
 * is the room strip; a value inside a view is `Segmented`. The chosen tab is 600 in the text colour with a 3 px line
 * under it, the others 500 muted; nothing else (no frame, no fill, no tick) says "chosen", so the blue focus ring is the
 * only ring. Each tab is at least 44 px high (48 to tap). Arrow keys, Home and End move focus; Enter, Space or a tap
 * chooses. The tabs are `aria-pressed` buttons in a labelled group, as before, so a view needs no tabpanel ids.
 *
 * `fit="equal"` shares the row in equal cells (Control's three tabs); `fit="content"` packs them from the start with
 * their own width, for a row that also holds tools at its end (Journal's Dag/Vecka beside + and ⋯). `rule` draws the
 * hairline under the tabs; turn it off when the row around them draws one across its full width. `wrap={false}` keeps
 * the tabs on one line (they overflow instead of wrapping), for a caller that measures whether they fit and swaps
 * in another control when they do not (Work's view picker); `ref` is the group element it measures.
 */
export type TabOption<T extends string = string> = {
  value: T;
  label: string;
};

export type TabsProps<T extends string = string> = {
  /** Accessible name of the group, in the caller's language. */
  label: string;
  options: readonly TabOption<T>[];
  /** The chosen tab. `null` (or a value not in `options`) means none is chosen. */
  value: T | null;
  onChange: (value: T) => void;
  disabled?: boolean;
  fit?: "equal" | "content";
  rule?: boolean;
  /** Wrap onto further lines when the tabs do not fit (default). `false` = one line, overflowing. */
  wrap?: boolean;
  className?: string;
  /** The group element, for a caller that measures it. */
  ref?: Ref<HTMLDivElement>;
};

export function Tabs<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled = false,
  fit = "equal",
  rule = true,
  wrap = true,
  className,
  ref,
}: TabsProps<T>) {
  const chosenIndex = options.findIndex((option) => option.value === value);
  const tabStop = chosenIndex === -1 ? 0 : chosenIndex;
  const classes = [
    "sk-tabs",
    `sk-tabs--${fit}`,
    rule ? "sk-tabs--rule" : "",
    wrap ? "" : "sk-tabs--nowrap",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <KeyScope
      roving
      ref={ref}
      role="group"
      aria-label={label}
      className={classes}
    >
      {options.map((option, index) => {
        const chosen = index === chosenIndex;
        return (
          <button
            key={option.value}
            type="button"
            className="sk-tabs__tab"
            data-label={option.label}
            aria-pressed={chosen}
            tabIndex={index === tabStop ? 0 : -1}
            disabled={disabled}
            onClick={() => {
              if (!chosen) onChange(option.value);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </KeyScope>
  );
}
