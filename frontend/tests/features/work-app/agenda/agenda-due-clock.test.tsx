import { agendaLabelsEn } from "@/features/work-app/agenda/agenda-labels";
import { fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkItemRecord } from "@/features/work-app/transport/transport";
import {
  TASK_ID,
  makeTransport,
  openMenu,
  openRow,
  renderAgenda,
  rowOf,
} from "@tests/helpers/agenda-triage-fixtures";

// 10:00 on the owner's clock on the 27th (CET): a Task Claude made with a time to be reminded at.
const TIMED = "2026-10-27T09:00:00.000Z";
const timed: WorkItemRecord = {
  kind: "task",
  id: TASK_ID,
  title: "Hämta paket på ICA",
  status: "todo",
  due_at: TIMED,
  version: 3,
  agenda_group: "overdue",
};

it("Tomorrow from a row's quick choices keeps the Task's time", async () => {
  const user = userEvent.setup();
  const { transport, updateTask } = makeTransport();
  renderAgenda([timed], transport);
  const { dates } = await openMenu(timed.title);
  await user.click(
    dates.getByRole("button", { name: agendaLabelsEn.triageTomorrow }),
  );
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      3,
      { due_at: "2026-10-30T09:00:00.000Z" },
      expect.any(String),
    ),
  );
});

it("a picked day from the row's date chip keeps the Task's time", async () => {
  const { transport, updateTask } = makeTransport();
  renderAgenda([timed], transport);
  openRow(timed.title);
  const menu = within(
    within(rowOf(timed.title)).getByRole("group", {
      name: agendaLabelsEn.rescheduleGroup,
    }),
  );
  fireEvent.input(menu.getByLabelText(workEn.rescheduleDate), {
    target: { value: "2026-11-05" },
  });
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      3,
      { due_at: "2026-11-05T09:00:00.000Z" },
      expect.any(String),
    ),
  );
});
