import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { expect, vi, type Mock } from "vitest";
import { AgendaView } from "@/features/work-app/agenda";
import { fillLabel } from "@/features/work-app/agenda-undo";
import { workEn } from "@/features/work-app/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport";

export const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
export const OTHER_ID = "019f0000-0000-7000-8000-0000000000a2";
export const DONE_ID = "019f0000-0000-7000-8000-0000000000a3";
export const PROJECT_ID = "019f0000-0000-7000-8000-0000000000b1";

export const task: WorkItemRecord = {
  kind: "task",
  id: TASK_ID,
  title: "Skicka offert",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "overdue",
};
export const other: WorkItemRecord = {
  kind: "task",
  id: OTHER_ID,
  title: "Boka målare",
  status: "in_progress",
  due_at: null,
  version: 4,
  agenda_group: "today",
};
export const done: WorkItemRecord = {
  kind: "task",
  id: DONE_ID,
  title: "Ring Anna om skåpen",
  status: "completed",
  due_at: "2026-10-24",
  version: 2,
  agenda_group: "overdue",
};
export const project: WorkItemRecord = {
  kind: "project",
  id: PROJECT_ID,
  title: "Kök",
  status: "active",
  due_at: null,
  version: 1,
  agenda_group: "today",
};

type Calls = { getTask: Mock; updateTask: Mock; getWorkAgenda: Mock };

/** The transport mock echoes the status and bumps the version; a test can override one call. */
export function makeTransport() {
  const mock: Calls = {
    getTask: vi.fn(),
    getWorkAgenda: vi.fn(),
    updateTask: vi.fn(
      (id: string, version: number, changes: { status: string }) =>
        Promise.resolve({
          task: {
            id,
            title: "",
            status: changes.status,
            due_at: null,
            version: version + 1,
          },
        }),
    ),
  };
  return { transport: mock as unknown as WorkTransport, mock };
}

export function renderAgenda(
  items: WorkItemRecord[],
  transport: WorkTransport,
  shortcuts = false,
  now?: Date,
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
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      shortcuts={shortcuts}
      now={now}
    />,
  );
}

export function glyphOf(title: string) {
  return screen.getByRole("button", {
    name: fillLabel(workEn.agendaComplete, { title }),
  });
}

export function rowOf(title: string): HTMLElement {
  const row = screen.getByRole("button", { name: title }).closest("li");
  if (!row) throw new Error(`no row for ${title}`);
  return row;
}

/** The Undo button once the write behind it has settled (the row is disabled while it runs). */
export async function undoButton() {
  const button = await screen.findByRole("button", { name: workEn.agendaUndo });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

/**
 * The Undo line of a row ("Done" in its status line, Undo beside it) once the write behind it has settled. The
 * status line is text only; Undo is its sibling in the row's `.work-agenda-undo` wrapper, not inside the line.
 */
export async function undoLineOf(title: string) {
  const button = await undoButton();
  const line = within(rowOf(title)).getByRole("status");
  expect(line.parentElement).toHaveClass("work-agenda-undo");
  expect(line.parentElement).toContainElement(button);
  expect(line).not.toContainElement(button);
  return line;
}

/** Opens a row's quick choices with a right click, the same gesture as a long press on touch. */
export function openRow(title: string) {
  fireEvent.contextMenu(rowOf(title));
}

/** Run after each test: real timers, no row-menu mark and an empty local store. */
export function resetAgendaEnvironment() {
  vi.useRealTimers();
  // A long press or right click marks the row menu as used, and the tip under the list leaves with it.
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
}
