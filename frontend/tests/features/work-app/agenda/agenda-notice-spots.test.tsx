import {
  boardLabelsEn,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";
import {
  glyphOf,
  makeTransport,
  other,
  renderAgenda,
  resetAgendaEnvironment,
  rowOf,
  task,
} from "@tests/helpers/agenda-view-fixtures";

/*
 * A failed write or read of the agenda says so where it was made: in the row that was written (naming its Task), at
 * "Flytta alla", and below "Visa fler", each with Try again that takes focus. Simulated host: this proves the
 * wiring, not a real Claude or Android host.
 */

afterEach(resetAgendaEnvironment);

const overdue = (id: string, title: string): WorkItemRecord => ({
  kind: "task",
  id,
  title,
  status: "todo",
  due_at: "2026-10-20T09:00:00",
  version: 3,
  agenda_group: "overdue",
});

it("a failed tick stands in its own row, names the Task and puts focus on Try again", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  mock.updateTask.mockRejectedValueOnce(new Error("network"));
  renderAgenda([task, other], transport);
  await user.click(glyphOf(task.title));
  const alert = await screen.findByRole("alert");
  expect(rowOf(task.title)).toContainElement(alert);
  expect(alert).toHaveTextContent(boardLabelsEn.rowChangeFailed(task.title));
  expect(alert).toHaveClass("sk-error--row");
  const retry = within(alert).getByRole("button", { name: workEn.retry });
  expect(retry).toHaveFocus();
  expect(within(rowOf(other.title)).queryByRole("alert")).toBeNull();
  // Try again repeats the write, and the line goes with it.
  await user.click(retry);
  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});

it("a failed tick names the Task in Swedish too", () => {
  expect(boardLabelsSv.rowChangeFailed("Skicka offert")).toBe(
    "Det gick inte att ändra ”Skicka offert”.",
  );
  expect(boardLabelsEn.rowChangeFailed("Send quote")).toBe(
    "Couldn’t change “Send quote”.",
  );
});

it("a failed Flytta alla stands under its button with Try again in focus", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  const reschedule = vi.fn().mockRejectedValueOnce(new Error("network"));
  Object.assign(mock, {
    rescheduleTasks: reschedule,
    getWorkAgenda: vi.fn(() =>
      Promise.resolve({ items: [], next_cursor: null }),
    ),
  });
  renderAgenda(
    [overdue("t-1", "Ring banken"), overdue("t-2", "Betala hyran")],
    transport,
  );
  await user.click(
    screen.getByRole("button", { name: workEn.moveAllOverdue(2) }),
  );
  await user.click(
    screen.getByRole("button", { name: workEn.moveAllConfirmYes }),
  );
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(workEn.moveAllFailed);
  const group = alert.closest("section");
  expect(group).toContainElement(
    screen.getByRole("button", { name: workEn.moveAllOverdue(2) }),
  );
  expect(
    within(alert).getByRole("button", { name: workEn.retry }),
  ).toHaveFocus();
});

it("a failed Visa fler says so under the button, not as a failed refresh, and Try again reads more", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  const later = {
    items: [{ ...other, id: "t-9", title: "Fler" }],
    next_cursor: null,
  };
  mock.getWorkAgenda
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValue(later);
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items: [task], next_cursor: "c1" },
  };
  render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
    />,
  );
  const more = screen.getByRole("button", { name: workEn.more });
  await user.click(more);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(boardLabelsEn.moreFailed);
  expect(alert).not.toHaveTextContent(workEn.agendaUndo);
  expect(alert).toHaveClass("sk-error--row");
  expect(more.compareDocumentPosition(alert)).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
  const retry = within(alert).getByRole("button", { name: workEn.retry });
  expect(retry).toHaveFocus();
  await user.click(retry);
  await waitFor(() => expect(mock.getWorkAgenda).toHaveBeenCalledTimes(2));
  expect(mock.getWorkAgenda.mock.calls[1]?.[1]).toBe("c1");
});

it("words a failed Visa fler in Swedish", () => {
  expect(boardLabelsSv.moreFailed).toBe("Det gick inte att hämta fler.");
});
