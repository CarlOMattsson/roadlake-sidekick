import { screen, within } from "@testing-library/react";
import type userEvent from "@testing-library/user-event";

/*
 * The phone's column tabs (the "Show column" group of the single layout). A tab's accessible name is its status and
 * its count ("To do 2"). The chosen column is module state of the board (it survives a mount within one test file),
 * so a test that needs a column chooses it itself and never counts on the default.
 */

/** The tab of a status, found by its label whatever its count is. */
export function columnTab(label: string): HTMLElement {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return screen.getByRole("button", {
    name: new RegExp(`^${escaped}\\s+\\d+$`),
  });
}

/** Presses the tab of a status (a pressed tab stays pressed). */
export async function chooseColumn(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
): Promise<void> {
  await user.click(columnTab(label));
}

/** The tabs of the group, in order, each as `Status count`. */
export function tabNames(group: string): string[] {
  return within(screen.getByRole("group", { name: group }))
    .getAllByRole("button")
    .map((tab) => tab.textContent?.replace(/\s+/g, " ").trim() ?? "");
}
