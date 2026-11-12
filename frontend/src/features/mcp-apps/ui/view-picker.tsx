import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { ChevronDownIcon } from "./icons";
import { KeyScope } from "./key-scope";
import "./view-picker.css";

/**
 * The picker that stands in for a row of tabs that does not fit (designsystem §3 "Rumshuvud", "Rumsremsan"):
 * one button with the chosen option's name and ⌄ ("Status ⌄", "Arbete ⌄"), which opens a menu with the options as
 * `menuitemradio` and ✓ on the chosen one, in the form of the ⋯ menu (a full-width card under the row, in the page
 * flow). The room strip, Work's views and later Control's tabs use this one picker.
 *
 * It returns the button and the menu apart, so the caller puts the button in its row and the menu on a line of its own
 * under the row. Arrow keys, Home and End move between the items, Escape closes the menu and gives the focus back to the button, Tab / Shift+Tab close it and move on (no focus trap).
 */
export type PickerOption<T extends string = string> = {
  value: T;
  label: string;
};

export function useViewPicker<T extends string>({
  label,
  options,
  value,
  onChange,
  shown,
  className,
  reselect = false,
  placeholder,
}: {
  /** Accessible name of the menu, in the caller's language. */
  label: string;
  options: readonly PickerOption<T>[];
  value: T | undefined;
  onChange: (value: T) => void;
  /** False while the tabs fit: no button and no menu then. */
  shown: boolean;
  /** An extra class on the button, for the caller's tests. */
  className?: string;
  /** Also report a press on the chosen option (the room picker: the active room goes to its root). */
  reselect?: boolean;
  /** The button's words while no option is chosen (`value` undefined, e.g. "Rum" in Control); else the first option's. */
  placeholder?: string;
}): { button: ReactNode; menu: ReactNode } {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const tabbing = useRef(false);
  const [open, setOpen] = useState(false);
  const menuOpen = shown && open;
  const chosen = options.find((option) => option.value === value);

  // An opened menu puts the focus on the chosen option, or on the first one when none is chosen (Control).
  useEffect(() => {
    if (!menuOpen) return;
    const menu = menuRef.current;
    (
      menu?.querySelector<HTMLElement>('[aria-checked="true"]') ??
      menu?.querySelector<HTMLElement>("[role=menuitemradio]")
    )?.focus();
  }, [menuOpen]);

  function close() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Tab") {
      // WAI-ARIA menu button: Tab closes the menu and moves on naturally, no focus trap. The browser moves the
      // focus; the blur handler below closes the menu when it has left.
      tabbing.current = true;
      return;
    }
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>("[role=menuitemradio]"),
    );
    const at = items.indexOf(event.target as HTMLElement);
    const step: Record<string, number> = {
      ArrowDown: at + 1,
      ArrowRight: at + 1,
      ArrowUp: at - 1 + items.length,
      ArrowLeft: at - 1 + items.length,
      Home: 0,
      End: items.length - 1,
    };
    if (at === -1 || !(event.key in step)) return;
    event.preventDefault();
    items[step[event.key]! % items.length]?.focus();
  }

  const button = shown ? (
    <button
      ref={buttonRef}
      type="button"
      className={className ? `sk-pick ${className}` : "sk-pick"}
      aria-haspopup="menu"
      aria-expanded={menuOpen}
      aria-controls={menuId}
      onClick={() => setOpen(!open)}
    >
      {chosen?.label ?? placeholder ?? options[0]?.label}
      <ChevronDownIcon />
    </button>
  ) : null;

  const menu = menuOpen ? (
    <KeyScope
      ref={menuRef}
      id={menuId}
      role="menu"
      aria-label={label}
      className="sk-pick-menu"
      onEscape={close}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        // The focus left the menu: by Tab / Shift+Tab (also onto the button), or to somewhere else outside the menu
        // and its button (a click or a script). Close without taking the focus back.
        const to = event.relatedTarget as Node | null;
        const byTab = tabbing.current;
        tabbing.current = false;
        if (
          byTab
            ? !to || !menuRef.current?.contains(to)
            : to && !menuRef.current?.contains(to) && to !== buttonRef.current
        )
          setOpen(false);
      }}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="menuitemradio"
          className="sk-pick-item"
          aria-checked={option.value === value}
          tabIndex={-1}
          onClick={() => {
            close();
            if (reselect || option.value !== value) onChange(option.value);
          }}
        >
          {option.label}
          {option.value === value ? (
            <svg
              viewBox="0 0 24 24"
              width="24"
              height="24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
          ) : null}
        </button>
      ))}
    </KeyScope>
  ) : null;

  return { button, menu };
}
