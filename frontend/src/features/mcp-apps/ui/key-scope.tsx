import { type ComponentPropsWithRef, type KeyboardEvent } from "react";

import { useRovingFocus } from "./roving-focus";

type KeyScopeTag = "div" | "form";

type KeyScopeProps<T extends KeyScopeTag> = Omit<
  ComponentPropsWithRef<T>,
  "onKeyDown"
> & {
  /** The element to render. A `form` is for a group that must also be a real form. Defaults to `div`. */
  as?: T;
  /**
   * Runs when Escape bubbles up from a control inside the scope (see `onEscapeKey`). Leave it unset, for example
   * while the scope is closed, and Escape passes through.
   */
  onEscape?: () => void;
  /** The scope holds a row of buttons: the arrow keys, Home and End move focus between them (`useRovingFocus`). */
  roving?: boolean;
  /** Runs first for every key that bubbles up, for keys this component does not handle itself. */
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
};

/**
 * Escape pressed on or in a control runs `action`, unless a control inside already handled it (`defaultPrevented`)
 * or the key confirms an IME composition. A handled Escape stops its default action and further bubbling, so an
 * outer scope or a window shortcut does not also act on it. Use it directly on a control that is not inside a
 * `KeyScope` (a toggle button that also closes its panel with Escape).
 */
export function onEscapeKey(
  event: KeyboardEvent<HTMLElement>,
  action: () => void,
): void {
  if (
    event.key !== "Escape" ||
    event.defaultPrevented ||
    event.nativeEvent.isComposing
  )
    return;
  event.preventDefault();
  event.stopPropagation();
  action();
}

/**
 * A container that handles the keys bubbling up from the focusable controls inside it: Escape closes a popover,
 * sheet or form, and the arrow keys rove focus over a row of buttons. The container is not a control itself, so it
 * has no focus stop and no role of its own; give it `role="group"` and a label where it names a set of controls.
 * Keeps the keyboard behaviour in one place instead of an `onKeyDown` per container.
 */
export function KeyScope<T extends KeyScopeTag = "div">({
  as,
  onEscape,
  roving = false,
  onKeyDown,
  ...rest
}: KeyScopeProps<T>) {
  const rove = useRovingFocus();
  // The container is not a control; its handler only receives keys from the controls inside. jsx-a11y
  // sees an unknown component tag here, so the intent is stated in this comment and not in a lint disable.
  const Tag = (as ?? "div") as "div";

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    onKeyDown?.(event);
    if (roving) rove(event);
    if (onEscape) onEscapeKey(event, onEscape);
  }

  return (
    <Tag
      {...(rest as ComponentPropsWithRef<"div">)}
      onKeyDown={handleKeyDown}
    />
  );
}
