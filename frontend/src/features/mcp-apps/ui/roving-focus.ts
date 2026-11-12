import { useCallback, type KeyboardEvent } from "react";

/**
 * Roving focus for a row of buttons (tabs, segments): ArrowRight/ArrowDown move focus to the next
 * button, ArrowLeft/ArrowUp to the previous, both wrapping at the ends; Home and End jump to the first
 * and last. Only focus moves here: Enter and Space still press the focused button.
 *
 * Attach the returned handler to the element that holds the buttons. It reads the buttons from that
 * element on each key press, so the caller needs no ref. Keys bubbling up from anything else are ignored.
 */
export function useRovingFocus() {
  return useCallback((event: KeyboardEvent<HTMLElement>) => {
    const buttons = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
    );
    const current = buttons.indexOf(event.target as HTMLButtonElement);
    if (current === -1) return;

    let next: number;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = (current + 1) % buttons.length;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = (current - 1 + buttons.length) % buttons.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = buttons.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    buttons[next]?.focus();
  }, []);
}
