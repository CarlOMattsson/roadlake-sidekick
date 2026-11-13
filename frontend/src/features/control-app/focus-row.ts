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
    root.querySelectorAll<HTMLLIElement>("li.control-row"),
  );
  const start = Math.max(0, index);
  const order = [...rows.slice(start), ...rows.slice(0, start).reverse()];
  for (const row of order) {
    const button = row.querySelector("button");
    if (button) {
      button.focus();
      return;
    }
  }
  fallback?.focus();
}
