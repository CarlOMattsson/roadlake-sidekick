import type { KeyboardEvent } from "react";

/**
 * Enter in a single-line field runs `action` directly (`onKeyDown={(event) => onEnterKey(event, save)}`). The MCP Apps host may sandbox the app without
 * `allow-forms` (the spec only asks for `allow-scripts` and `allow-same-origin`), and then a `<form>` never
 * submits: neither Enter nor a submit button fires `onSubmit`. Fields and buttons in the apps therefore act on
 * their own key and click events and never rely on form submission. Enter that confirms an IME composition
 * is left alone, and the handled key calls `preventDefault` so no implicit submission follows.
 */
export function onEnterKey(event: KeyboardEvent, action: () => void): void {
  if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
  if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return;
  event.preventDefault();
  action();
}

/**
 * The `onSubmit` of a form that is only a semantic group: it never navigates when the host does allow
 * forms. The action runs from `onEnterKey` and the button's click instead.
 */
export function preventSubmit(event: { preventDefault(): void }): void {
  event.preventDefault();
}
