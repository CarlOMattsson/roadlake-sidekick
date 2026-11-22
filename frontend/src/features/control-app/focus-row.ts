/**
 * Moves focus to the button of the row at `index` (the row that took its place, or the one before
 * when it was last). A row without a button is skipped; with no button left, focus goes to `fallback`.
 */
export function focusRowNear(
  root: HTMLElement,
  index: number,
  fallback: HTMLElement | null,
) {
  const rows = Array.from(
    root.querySelectorAll<HTMLElement>("li.control-row, .control-trow"),
  );
  const start = Math.max(0, index);
  const order = [...rows.slice(start), ...rows.slice(0, start).reverse()];
  for (const row of order) {
    // A table row's open button is not the button a write left behind: Undo and Restore are.
    const button = row.querySelector<HTMLButtonElement>(
      "button:not(.control-topen)",
    );
    if (button) {
      button.focus();
      return;
    }
  }
  fallback?.focus();
}
