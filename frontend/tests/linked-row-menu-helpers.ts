import { fireEvent, within } from "@testing-library/react";

/**
 * Opens a linked row's own menu with a right click (the same `contextmenu` a long press on touch raises) and returns
 * its "Remove link" / "Ta bort koppling" button. A linked row (a Contact under a Task, a Project under a Contact) has no
 * ⋯; its menu holds the removal.
 */
export function openLinkedRowMenu(row: HTMLElement) {
  fireEvent.contextMenu(row);
  return within(row).findByRole("button", {
    name: /^(Remove link|Ta bort koppling)$/,
  });
}
