import { useLayoutEffect, useRef, useState } from "react";

import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { useViewPicker } from "../../mcp-apps/ui/view-picker";
import "./view-tabs.css";

/**
 * The view switcher of the Work shell (Agenda, Status, Projekt), designsystem §3 "Flikar" and "Rumshuvud": a row of
 * text tabs, 44 px high, with no background. The pressed tab has --sk-fg and a 2 px underline. It is a group of buttons
 * with `aria-pressed`; arrow keys, Home and End move focus only, Enter or Space (or a click) selects.
 *
 * When the tabs do not fit beside the tools (measured, never by breakpoint: 320 px, text at 200 %), the row gives way
 * to the view picker (ui/view-picker.tsx): "Status ⌄", a menu with the views and ✓ on the chosen one. No label is
 * ever cut and nothing scrolls. The tab row stays mounted, hidden at the same width, so it keeps measuring whether it fits again.
 */
export type ViewTabOption<T extends string = string> = {
  value: T;
  label: string;
};

export function ViewTabs<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  /** Accessible name of the group and of the picker's menu, in the caller's language. */
  label: string;
  options: readonly ViewTabOption<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  const groupRef = useRef<HTMLDivElement>(null);
  const pressedIndex = options.findIndex((option) => option.value === value);
  const tabStopIndex = pressedIndex === -1 ? 0 : pressedIndex;
  const [narrow, setNarrow] = useState(false);
  const picker = useViewPicker({
    label,
    options,
    value,
    onChange,
    shown: narrow,
    className: "work-view-pick",
  });

  // Whether the tabs fit: read before paint, and again whenever the row or a label changes size (font load, text
  // zoom). The row has the same width shown or hidden, so the answer never depends on which one is shown.
  useLayoutEffect(() => {
    const row = groupRef.current;
    if (!row) return;
    const fit = () => setNarrow(row.scrollWidth > row.clientWidth + 1);
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const sizes = new ResizeObserver(fit);
    sizes.observe(row);
    for (const tab of Array.from(row.children)) sizes.observe(tab);
    return () => sizes.disconnect();
  }, [options.length]);

  return (
    <>
      <div className="work-view-tabs-wrap">
        <KeyScope
          roving
          ref={groupRef}
          role="group"
          aria-label={label}
          className="work-view-tabs"
          data-narrow={narrow || undefined}
        >
          {options.map((option, index) => (
            <button
              key={option.value}
              type="button"
              className="work-view-tabs__tab"
              aria-pressed={index === pressedIndex}
              tabIndex={index === tabStopIndex ? 0 : -1}
              onClick={() => {
                if (index !== pressedIndex) onChange(option.value);
              }}
            >
              {option.label}
            </button>
          ))}
        </KeyScope>
        {picker.button}
      </div>
      {picker.menu}
    </>
  );
}
