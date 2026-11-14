import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type { WorkItemRecord } from "@/features/work-app/transport/transport";
import {
  makeTransport,
  renderAgenda,
  resetAgendaEnvironment,
} from "@tests/helpers/agenda-view-fixtures";

afterEach(resetAgendaEnvironment);

const overdue = (id: string, title: string, due: string): WorkItemRecord => ({
  kind: "task",
  id,
  title,
  status: "todo",
  due_at: due,
  version: 3,
  agenda_group: "overdue",
});
const ring = overdue("t-1", "Ring banken", "2026-10-20T09:00:00");
const pay = overdue("t-2", "Betala hyran", "2026-10-21T09:00:00");
const moveAllButton = () =>
  screen.getByRole("button", { name: workEn.moveAllOverdue(2) });

/** The transport answers a reschedule with each Task one version on, and the agenda read with no overdue left. */
function setup() {
  const { transport, mock } = makeTransport();
  const reschedule = vi.fn(() =>
    Promise.resolve({
      count: 2,
      tasks: [
        { id: "t-1", version: 4, due_at: "2026-10-29T23:59:00" },
        { id: "t-2", version: 4, due_at: "2026-10-29T23:59:00" },
      ],
    }),
  );
  const agenda = vi.fn(() => Promise.resolve({ items: [], next_cursor: null }));
  Object.assign(mock, { rescheduleTasks: reschedule, getWorkAgenda: agenda });
  renderAgenda([ring, pay], transport);
  return { mock, reschedule, agenda };
}

/** Taps the move-all button and confirms. */
async function moveAll(user: ReturnType<typeof userEvent.setup>) {
  await user.click(moveAllButton());
  await user.click(
    screen.getByRole("button", { name: workEn.moveAllConfirmYes }),
  );
}

it("asks before moving: the question replaces the button, focus is on Move, and Cancel and Escape write nothing and give the button back with focus", async () => {
  const user = userEvent.setup();
  const { reschedule } = setup();
  await user.click(moveAllButton());
  expect(screen.getByText(workEn.moveAllConfirm(2))).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: workEn.moveAllOverdue(2) }),
  ).toBeNull();
  expect(
    screen.getByRole("button", { name: workEn.moveAllConfirmYes }),
  ).toHaveFocus();
  await user.click(screen.getByRole("button", { name: workEn.cancel }));
  expect(moveAllButton()).toHaveFocus();
  await user.click(moveAllButton());
  await user.keyboard("{Escape}");
  expect(moveAllButton()).toHaveFocus();
  expect(reschedule).not.toHaveBeenCalled();
});

it("writes once on Move, shows the count with Undo, and Undo writes each old due date back against the version the move left", async () => {
  const user = userEvent.setup();
  const { mock, reschedule, agenda } = setup();
  await moveAll(user);
  await waitFor(() => expect(reschedule).toHaveBeenCalledTimes(1));
  const status = await screen.findByText(workEn.moveAllDone(2));
  expect(status).toHaveAttribute("role", "status");
  await waitFor(() => expect(agenda).toHaveBeenCalledTimes(1));
  const undo = within(status.parentElement as HTMLElement).getByRole("button", {
    name: workEn.agendaUndo,
  });
  await waitFor(() => expect(undo).toBeEnabled());
  await user.click(undo);
  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(2));
  const calls = mock.updateTask.mock.calls as unknown[][];
  expect(calls.map(([id, version, changes]) => [id, version, changes])).toEqual(
    [
      ["t-1", 4, { due_at: "2026-10-20T09:00:00" }],
      ["t-2", 4, { due_at: "2026-10-21T09:00:00" }],
    ],
  );
  expect(new Set(calls.map((call) => call[3])).size).toBe(2);
  await waitFor(() => expect(agenda).toHaveBeenCalledTimes(2));
  expect(screen.queryByText(workEn.moveAllDone(2))).toBeNull();
  expect(reschedule).toHaveBeenCalledTimes(1);
});

it("a failed move says so in its own words and Try again moves again", async () => {
  const user = userEvent.setup();
  const { reschedule } = setup();
  reschedule.mockRejectedValueOnce(new Error("network"));
  await moveAll(user);
  expect(await screen.findByText(workEn.moveAllFailed)).toBeInTheDocument();
  expect(screen.queryByText(boardLabelsEn.moveFailed)).toBeNull();
  // A failed change is the family's write error row, not the refresh row of a failed read.
  expect(screen.getByRole("alert")).toHaveClass("sk-error--row");
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(reschedule).toHaveBeenCalledTimes(2));
  expect(await screen.findByText(workEn.moveAllDone(2))).toBeInTheDocument();
});

it("a failed Undo says the same and Try again writes back only what is not back yet", async () => {
  const user = userEvent.setup();
  const { mock } = setup();
  mock.updateTask
    .mockResolvedValueOnce({ task: { id: "t-1", version: 5 } })
    .mockRejectedValueOnce(new Error("network"));
  await moveAll(user);
  const undo = await screen.findByRole("button", { name: workEn.agendaUndo });
  await waitFor(() => expect(undo).toBeEnabled());
  await user.click(undo);
  expect(await screen.findByText(workEn.moveAllFailed)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(3));
  expect((mock.updateTask.mock.calls as unknown[][])[2]?.[0]).toBe("t-2");
});

it("words the question, the confirming button and the done line in Swedish and English", () => {
  expect(workSv.moveAllConfirm(3)).toBe("Flytta 3 till imorgon?");
  expect(workEn.moveAllConfirm(3)).toBe("Move 3 tasks to tomorrow?");
  expect(workSv.moveAllConfirmYes).toBe("Flytta");
  expect(workSv.moveAllDone(3)).toBe("3 flyttade till imorgon");
  expect(workSv.moveAllDone(1)).toBe("1 flyttad till imorgon");
  expect(workEn.moveAllDone(3)).toBe("Moved 3 tasks to tomorrow");
  expect(workSv.moveAllFailed).toBe("Det gick inte att flytta de försenade.");
  expect(workEn.moveAllFailed).toBe("Couldn’t move the overdue tasks.");
});
