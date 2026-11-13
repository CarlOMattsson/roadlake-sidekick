import { agendaLabelsFor } from "@/features/work-app/agenda/agenda-labels";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { expect, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { workEn, type WorkLabels } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";

export const TASK_ID = "019f0000-0000-7000-8000-0000000000c1";
export const OTHER_ID = "019f0000-0000-7000-8000-0000000000c2";
export const DUE = "2026-10-27T09:00:00.000Z";
// Thursday 29 October 2026, 10:00 local time.
export const NOW = new Date(2026, 9, 29, 10, 0);

export const overdue: WorkItemRecord = {
  kind: "task",
  id: TASK_ID,
  title: "Betala fakturan",
  status: "todo",
  due_at: DUE,
  version: 3,
  agenda_group: "overdue",
};
export const todayTask: WorkItemRecord = {
  kind: "task",
  id: OTHER_ID,
  title: "Boka målare",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "today",
};

/** The transport echoes the change: a due move returns the due instant it was given. */
export function makeTransport() {
  const updateTask = vi.fn(
    (id: string, version: number, changes: WorkTaskChanges) =>
      Promise.resolve({
        task: {
          id,
          title: "",
          status: changes.status ?? "todo",
          due_at: changes.due_at !== undefined ? changes.due_at : DUE,
          version: version + 1,
        },
      }),
  );
  const getWorkAgenda = vi.fn(() =>
    Promise.resolve({ items: [], next_cursor: null }),
  );
  const transport = {
    updateTask,
    getTask: vi.fn(),
    getWorkAgenda,
  } as unknown as WorkTransport;
  return { transport, updateTask, getWorkAgenda };
}

export function renderAgenda(
  items: WorkItemRecord[],
  transport: WorkTransport,
  labels: WorkLabels = workEn,
) {
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items, next_cursor: null },
  };
  return render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={labels}
      moves={0}
      onOpen={vi.fn()}
      now={NOW}
    />,
  );
}

export function rowOf(title: string): HTMLElement {
  const row = screen.getByRole("button", { name: title }).closest("li");
  if (!row) throw new Error(`no row for ${title}`);
  return row;
}

/**
 * Opens the quick choices of a row (a right click, the long press of touch), once its write has settled, and
 * returns the choices' two groups: the status choices and the New date choices (Tomorrow, Next week, Choose …).
 * A move or an Undo closes them, so a second call opens them again.
 */
export async function openMenu(title: string, labels: WorkLabels = workEn) {
  const row = within(rowOf(title));
  await waitFor(() =>
    expect(row.getByRole("button", { name: title })).toBeEnabled(),
  );
  fireEvent.contextMenu(rowOf(title));
  return {
    status: within(row.getByRole("group", { name: labels.status })),
    dates: within(
      row.getByRole("group", {
        name: agendaLabelsFor(labels.dateLocale).rescheduleGroup,
      }),
    ),
  };
}

/** Opens a row's quick choices with a right click, the same gesture as a long press on touch. */
export function openRow(title: string) {
  fireEvent.contextMenu(rowOf(title));
}

/** The Undo button once the write behind it has settled (the row is disabled while it runs). */
export async function undoButton() {
  const button = await screen.findByRole("button", { name: /^Undo/ });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

/**
 * The Undo line of a row once the write behind it has settled. The line is a `role="status"` paragraph with the
 * text only; the Undo button is its sibling in the row's `.work-agenda-undo` wrapper, not inside the line.
 */
export async function undoLineOf(title: string) {
  const button = await undoButton();
  const line = within(rowOf(title)).getByRole("status");
  expect(line.parentElement).toHaveClass("work-agenda-undo");
  expect(line.parentElement).toContainElement(button);
  expect(line).not.toContainElement(button);
  return line;
}
