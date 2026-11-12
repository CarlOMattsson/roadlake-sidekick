import { readFileSync } from "node:fs";
import path from "node:path";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fillLabel, UNDO_MS } from "@/features/work-app/agenda-undo";
import { triageDueAt } from "@/features/work-app/work-items";
import { workEn, workSv } from "@/features/work-app/labels";
import type { WorkItemRecord } from "@/features/work-app/transport";
import {
  TASK_ID,
  OTHER_ID,
  DUE,
  NOW,
  overdue,
  todayTask,
  makeTransport,
  renderAgenda,
  rowOf,
  openMenu,
  openRow,
  undoButton,
  undoLineOf,
} from "./helpers/agenda-triage-fixtures";

afterEach(() => {
  // A right click marks the row menu as used, and the tip under the list leaves with it.
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});

it("an overdue Task keeps Tomorrow, Next week and Done off its row; its quick choices offer them", async () => {
  const { transport } = makeTransport();
  renderAgenda([overdue, todayTask], transport);
  const row = within(rowOf(overdue.title));
  expect(
    row.queryByRole("button", { name: workEn.triageTomorrow }),
  ).not.toBeInTheDocument();
  expect(
    row.queryByRole("button", { name: workEn.triageNextWeek }),
  ).not.toBeInTheDocument();
  // Done is the status choice "Done" (taskStatus.completed) in the quick choices, not a row button of its own.
  expect(
    row.queryByRole("button", { name: workEn.taskStatus.completed }),
  ).not.toBeInTheDocument();
  const { status, dates } = await openMenu(overdue.title);
  expect(
    dates.getByRole("button", { name: workEn.triageTomorrow }),
  ).toBeEnabled();
  expect(
    dates.getByRole("button", { name: workEn.triageNextWeek }),
  ).toBeEnabled();
  expect(
    status.getByRole("button", { name: workEn.taskStatus.completed }),
  ).toBeEnabled();
});

it("Tomorrow writes 23:59 local time tomorrow at the version the row shows, and Undo names the move", async () => {
  const user = userEvent.setup();
  const { transport, updateTask } = makeTransport();
  renderAgenda([overdue], transport);
  const { dates } = await openMenu(overdue.title);
  await user.click(dates.getByRole("button", { name: workEn.triageTomorrow }));
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      3,
      { due_at: new Date(2026, 9, 30, 23, 59).toISOString() },
      expect.any(String),
    ),
  );
  const line = await undoLineOf(overdue.title);
  expect(line).toHaveTextContent("Moved to tomorrow");
});

it("Next week writes 23:59 on the Monday of next week, which is 2 November from Thursday 29 October", async () => {
  const user = userEvent.setup();
  const { transport, updateTask } = makeTransport();
  renderAgenda([overdue], transport);
  const { dates } = await openMenu(overdue.title);
  await user.click(dates.getByRole("button", { name: workEn.triageNextWeek }));
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      3,
      { due_at: new Date(2026, 10, 2, 23, 59).toISOString() },
      expect.any(String),
    ),
  );
  const line = await undoLineOf(overdue.title);
  expect(line).toHaveTextContent("Moved to Mon 2 Nov");
});

it("a due move keeps the row in its group, muted with its new date, and its date choices are off until the list is read again", async () => {
  const user = userEvent.setup();
  const { transport, getWorkAgenda } = makeTransport();
  renderAgenda([overdue], transport);
  const { dates } = await openMenu(overdue.title);
  await user.click(dates.getByRole("button", { name: workEn.triageTomorrow }));
  // The row stays in Försenade, under the group's line: its Undo line says the new date, with Undo beside it,
  // and the row is muted.
  const line = await undoLineOf(overdue.title);
  expect(line).toHaveTextContent("Moved to tomorrow");
  expect(rowOf(overdue.title)).toHaveClass("work-agenda-row-moved");
  // The move closed the menu; opened again, its date choices are off.
  const again = (await openMenu(overdue.title)).dates;
  expect(
    again.getByRole("button", { name: workEn.triageTomorrow }),
  ).toBeDisabled();
  expect(
    again.getByRole("button", { name: workEn.triageNextWeek }),
  ).toBeDisabled();
  expect(again.getByLabelText(workEn.rescheduleDate)).toBeDisabled();
  // The list reads again: the row is no longer muted and the date choices are on again.
  await user.click(screen.getByRole("button", { name: workEn.refresh }));
  await waitFor(() => expect(getWorkAgenda).toHaveBeenCalledTimes(1));
  // The open row goes back above the line, a new list item: its choices are read from the row as it is now.
  await waitFor(() =>
    expect(
      within(rowOf(overdue.title)).getByRole("button", {
        name: workEn.triageTomorrow,
      }),
    ).toBeEnabled(),
  );
  expect(rowOf(overdue.title)).not.toHaveClass("work-agenda-row-moved");
});

it("Done in the quick choices leaves the row in its group, muted, with Undo beside its status, and its date choices are off", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([overdue], transport);
  const { status } = await openMenu(overdue.title);
  await user.click(
    status.getByRole("button", { name: workEn.taskStatus.completed }),
  );
  const line = await undoLineOf(overdue.title);
  expect(line).toHaveTextContent(workEn.taskStatus.completed);
  expect(rowOf(overdue.title)).toHaveClass("work-agenda-row-moved");
  const { dates } = await openMenu(overdue.title);
  expect(
    dates.getByRole("button", { name: workEn.triageTomorrow }),
  ).toBeDisabled();
  expect(
    dates.getByRole("button", { name: workEn.triageNextWeek }),
  ).toBeDisabled();
});

it("Undo of a due move turns the row back: no note, and its date choices are on again", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([overdue], transport);
  const { dates } = await openMenu(overdue.title);
  await user.click(dates.getByRole("button", { name: workEn.triageTomorrow }));
  await user.click(await undoButton());
  // Undo closes the menu; opened again, its date choices are on.
  const again = (await openMenu(overdue.title)).dates;
  await waitFor(() =>
    expect(
      again.getByRole("button", { name: workEn.triageTomorrow }),
    ).toBeEnabled(),
  );
  expect(rowOf(overdue.title).querySelector(".work-agenda-moved")).toBeNull();
});

it("when its Undo time is up, a due move's row keeps the new date as its note, muted, until the list is read again", async () => {
  vi.useFakeTimers();
  const { transport } = makeTransport();
  renderAgenda([overdue], transport);
  fireEvent.contextMenu(rowOf(overdue.title));
  fireEvent.click(
    within(
      screen.getByRole("group", { name: workEn.rescheduleGroup }),
    ).getByRole("button", { name: workEn.triageTomorrow }),
  );
  // Lets the write settle under fake timers; waitFor would hang here because it polls with timers.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(rowOf(overdue.title).querySelector(".work-agenda-moved")).toBeNull();
  act(() => {
    vi.advanceTimersByTime(UNDO_MS);
  });
  expect(
    screen.queryByRole("button", { name: workEn.agendaUndo }),
  ).not.toBeInTheDocument();
  expect(rowOf(overdue.title)).toHaveClass("work-agenda-row-moved");
  expect(
    rowOf(overdue.title).querySelector(".work-agenda-moved"),
  ).toHaveTextContent(fillLabel(workEn.movedTo, { status: "tomorrow" }));
  vi.useRealTimers();
});

it("the Undo line of a due move reads 'Flyttad till imorgon' in Swedish, with the date part in lower case", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  renderAgenda([overdue], transport, workSv);
  const { dates } = await openMenu(overdue.title, workSv);
  await user.click(dates.getByRole("button", { name: "Imorgon" }));
  await screen.findByRole("button", { name: workSv.agendaUndo });
  const line = within(rowOf(overdue.title)).getByRole("status");
  expect(line).toHaveTextContent("Flyttad till imorgon");
});

it("the triage instants are 23:59 local, and next week is always a later Monday", () => {
  // Monday 26 October: next week starts on Monday 2 November, not on the same day.
  expect(triageDueAt(new Date(2026, 9, 26, 10), "nextWeek")).toBe(
    new Date(2026, 10, 2, 23, 59).toISOString(),
  );
  // Sunday 1 November: tomorrow and next week are the same Monday.
  expect(triageDueAt(new Date(2026, 10, 1, 10), "tomorrow")).toBe(
    new Date(2026, 10, 2, 23, 59).toISOString(),
  );
  expect(triageDueAt(new Date(2026, 10, 1, 10), "nextWeek")).toBe(
    new Date(2026, 10, 2, 23, 59).toISOString(),
  );
  // Thursday 29 October: tomorrow is Friday 30 October at 23:59.
  expect(triageDueAt(NOW, "tomorrow")).toBe(
    new Date(2026, 9, 30, 23, 59).toISOString(),
  );
});

it("the Idag instant is 23:59 local on the same day, also late in the day", () => {
  expect(triageDueAt(NOW, "today")).toBe(
    new Date(2026, 9, 29, 23, 59).toISOString(),
  );
  expect(triageDueAt(new Date(2026, 9, 29, 23, 30), "today")).toBe(
    new Date(2026, 9, 29, 23, 59).toISOString(),
  );
});

it("Done in the quick choices marks the Task completed as the glyph does, and the choice is pressed once the Task is done", async () => {
  const user = userEvent.setup();
  const { transport, updateTask } = makeTransport();
  const { unmount } = renderAgenda([overdue], transport);
  const { status } = await openMenu(overdue.title);
  await user.click(
    status.getByRole("button", { name: workEn.taskStatus.completed }),
  );
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      3,
      { status: "completed" },
      expect.any(String),
    ),
  );
  unmount();
  const done = makeTransport();
  renderAgenda([{ ...overdue, status: "completed" }], done.transport);
  const doneMenu = await openMenu(overdue.title);
  expect(
    doneMenu.status.getByRole("button", { name: workEn.taskStatus.completed }),
  ).toHaveAttribute("aria-pressed", "true");
});

it("Undo of a due move writes the old due date back at the version the move left, with a new key", async () => {
  const user = userEvent.setup();
  const { transport, updateTask } = makeTransport();
  renderAgenda([overdue], transport);
  const { dates } = await openMenu(overdue.title);
  await user.click(dates.getByRole("button", { name: workEn.triageTomorrow }));
  await user.click(await undoButton());
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  expect(updateTask).toHaveBeenLastCalledWith(
    TASK_ID,
    4,
    { due_at: DUE },
    expect.any(String),
  );
  const [first, second] = updateTask.mock.calls as unknown[][];
  expect((second as unknown[])[3]).not.toBe((first as unknown[])[3]);
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).not.toBeInTheDocument(),
  );
});

it("the quick choices carry Imorgon, Nästa vecka and Klar in Swedish, and the row has no triage buttons", async () => {
  const { transport } = makeTransport();
  renderAgenda([overdue], transport, workSv);
  expect(
    within(rowOf(overdue.title)).queryByRole("button", { name: "Imorgon" }),
  ).not.toBeInTheDocument();
  const { status, dates } = await openMenu(overdue.title, workSv);
  expect(dates.getByRole("button", { name: "Imorgon" })).toBeInTheDocument();
  expect(
    dates.getByRole("button", { name: "Nästa vecka" }),
  ).toBeInTheDocument();
  expect(status.getByRole("button", { name: "Klar" })).toBeInTheDocument();
});

it("the English and Swedish triage labels are set in labels.ts", () => {
  expect(workEn.triageTomorrow).toBe("Tomorrow");
  expect(workEn.triageNextWeek).toBe("Next week");
  expect(workSv.triageTomorrow).toBe("Imorgon");
  expect(workSv.triageNextWeek).toBe("Nästa vecka");
  // The quick choices name their two rows "Status" and "Datum"/"Date"; "Välj datum …" opens the date field.
  expect(workEn.rescheduleGroup).toBe("New date");
  expect(workEn.rescheduleRow).toBe("Date");
  expect(workEn.rescheduleChoose).toBe("Choose date…");
  expect(workSv.rescheduleGroup).toBe("Nytt datum");
  expect(workSv.rescheduleRow).toBe("Datum");
  expect(workSv.rescheduleChoose).toBe("Välj datum …");
  expect(workSv.rescheduleDate).toBe("Välj datum");
});

it("the quick choices of a Task that is not overdue offer New date: Tomorrow writes 23:59 tomorrow and Undo names the move", async () => {
  const user = userEvent.setup();
  const { transport, updateTask } = makeTransport();
  renderAgenda([todayTask], transport);
  openRow(todayTask.title);
  const menu = within(
    screen.getByRole("group", { name: workEn.rescheduleGroup }),
  );
  expect(
    menu.getByRole("button", { name: workEn.triageTomorrow }),
  ).toBeEnabled();
  expect(
    menu.getByRole("button", { name: workEn.triageNextWeek }),
  ).toBeEnabled();
  expect(menu.getByLabelText(workEn.rescheduleDate)).toBeEnabled();
  await user.click(menu.getByRole("button", { name: workEn.triageTomorrow }));
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      OTHER_ID,
      1,
      { due_at: new Date(2026, 9, 30, 23, 59).toISOString() },
      expect.any(String),
    ),
  );
  const line = await undoLineOf(todayTask.title);
  expect(line).toHaveTextContent("Moved to tomorrow");
  // The move closes the quick choices, as a status change does.
  expect(
    screen.queryByRole("group", { name: workEn.rescheduleGroup }),
  ).not.toBeInTheDocument();
});

it("the Choose date… chip is the date input itself, laid over the chip, and a picked day writes 23:59 on that day", async () => {
  const { transport, updateTask } = makeTransport();
  renderAgenda([todayTask], transport);
  openRow(todayTask.title);
  const menu = within(
    screen.getByRole("group", { name: workEn.rescheduleGroup }),
  );
  // No click first: the input is there from the start, over the chip, which is not a button of its own.
  const input = menu.getByLabelText(workEn.rescheduleDate);
  expect(input).toHaveAttribute("type", "date");
  expect(input).toHaveClass("work-agenda-date-input");
  const chip = input.closest(".work-agenda-date-chip") as HTMLElement;
  expect(chip).toHaveClass("sk-chip");
  expect(chip).toHaveTextContent(workEn.rescheduleChoose);
  expect(
    menu.queryByRole("button", { name: workEn.rescheduleChoose }),
  ).not.toBeInTheDocument();
  fireEvent.change(input, {
    target: { value: "2026-11-05" },
  });
  await waitFor(() =>
    expect(updateTask).toHaveBeenCalledWith(
      OTHER_ID,
      1,
      // 23:59 on 5 Nov in Europe/Stockholm (CET, +01:00), not in the browser's own zone.
      { due_at: "2026-11-05T22:59:00.000Z" },
      expect.any(String),
    ),
  );
});

describe("the date chip writes only an intended choice", () => {
  async function prefilled() {
    const { transport, updateTask } = makeTransport();
    renderAgenda([overdue, todayTask], transport);
    const { dates } = await openMenu(overdue.title);
    const input = dates.getByLabelText(workEn.rescheduleDate);
    // The Task's own day (27 Oct) is in the field, so the picker opens on it.
    expect(input).toHaveValue("2026-10-27");
    act(() => input.focus());
    return { input, updateTask };
  }

  it("several input events in a row from the keys write nothing until Enter, then one complete date", async () => {
    const { input, updateTask } = await prefilled();
    // Typing the month "1" (meant 11) gives a valid date at once in a prefilled field; so does each arrow press.
    fireEvent.keyDown(input, { key: "1" });
    fireEvent.input(input, { target: { value: "2026-01-27" } });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.input(input, { target: { value: "2026-01-28" } });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.input(input, { target: { value: "2026-01-29" } });
    fireEvent.keyDown(input, { key: "Backspace" });
    fireEvent.input(input, { target: { value: "" } });
    fireEvent.keyDown(input, { key: "1" });
    fireEvent.input(input, { target: { value: "2026-11-27" } });
    await Promise.resolve();
    expect(updateTask).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      3,
      { due_at: "2026-11-27T22:59:00.000Z" },
      expect.any(String),
    );
  });

  it("a typed date is written on blur, but an incomplete or unchanged one is not, and the field goes back to the Task's date", async () => {
    const { input, updateTask } = await prefilled();
    fireEvent.keyDown(input, { key: "Backspace" });
    fireEvent.input(input, { target: { value: "" } });
    fireEvent.blur(input);
    expect(input).toHaveValue("2026-10-27");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.input(input, { target: { value: "2026-10-27" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(updateTask).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.input(input, { target: { value: "2026-10-28" } });
    fireEvent.blur(input);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  });

  it("a picked date (a change with no key before it) writes at once, and the field shows the Task's date again until the write lands", async () => {
    const { input, updateTask } = await prefilled();
    fireEvent.change(input, { target: { value: "2026-12-24" } });
    expect(input).toHaveValue("2026-10-27");
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        TASK_ID,
        3,
        { due_at: "2026-12-24T22:59:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("a click asks for the picker (showPicker, also without the browser's indicator); a refusal changes nothing, and Enter still types", async () => {
    const { input, updateTask } = await prefilled();
    const showPicker = vi.fn();
    Object.defineProperty(input, "showPicker", {
      configurable: true,
      value: showPicker,
    });
    fireEvent.click(input);
    expect(showPicker).toHaveBeenCalledTimes(1);
    showPicker.mockImplementation(() => {
      throw new DOMException("refused", "NotAllowedError");
    });
    expect(() => fireEvent.click(input)).not.toThrow();
    // A refused picker leaves Enter to the field: a typed date is then written by Enter.
    fireEvent.keyDown(input, { key: "2" });
    fireEvent.input(input, { target: { value: "2026-10-29" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(showPicker).toHaveBeenCalledTimes(2);
  });
});

it("the quick choices of an overdue Task offer Done as well, as those of another Task do, and only one row's choices are open", async () => {
  const { transport } = makeTransport();
  renderAgenda([overdue, todayTask], transport);
  const overdueMenu = await openMenu(overdue.title);
  expect(
    overdueMenu.status.getByRole("button", {
      name: workEn.taskStatus.completed,
    }),
  ).toBeEnabled();
  expect(
    overdueMenu.status.getByRole("button", { name: workEn.taskStatus.blocked }),
  ).toBeInTheDocument();
  const todayMenu = await openMenu(todayTask.title);
  expect(
    todayMenu.status.getByRole("button", { name: workEn.taskStatus.completed }),
  ).toBeEnabled();
  // Opening the other row's choices closes the overdue row's.
  expect(screen.getAllByRole("group", { name: workEn.status })).toHaveLength(1);
  expect(
    within(rowOf(overdue.title)).queryByRole("group", {
      name: workEn.status,
    }),
  ).not.toBeInTheDocument();
});

it("the date group always shows Idag, Imorgon, Nästa vecka and Välj datum …; a date outside them is a fifth chip first, chosen", async () => {
  const { transport, updateTask } = makeTransport();
  renderAgenda([overdue, todayTask], transport, workSv);
  const { dates } = await openMenu(overdue.title, workSv);
  const buttons = dates.getAllByRole("button");
  expect(buttons.map((button) => button.textContent)).toEqual([
    "tis 27 okt",
    workSv.agendaGroup.today,
    workSv.triageTomorrow,
    workSv.triageNextWeek,
  ]);
  // The Task's own date is the one chosen chip; the shortcuts are not. Välj datum … is the date input over a chip
  // (not a button), holding the Task's date.
  expect(buttons.map((button) => button.getAttribute("aria-pressed"))).toEqual([
    "true",
    "false",
    "false",
    "false",
  ]);
  const choose = dates.getByLabelText(workSv.rescheduleDate);
  expect(choose).toHaveValue("2026-10-27");
  expect(choose.closest(".work-agenda-date-chip")).toHaveTextContent(
    workSv.rescheduleChoose,
  );
  await userEvent.click(buttons[0] as HTMLElement);
  expect(updateTask).not.toHaveBeenCalled();
});

it("a Task due on one of the shortcuts has that chip chosen and no fifth chip; the chosen chip does nothing when tapped", async () => {
  const { transport, updateTask } = makeTransport();
  const dueToday: WorkItemRecord = {
    ...todayTask,
    due_at: triageDueAt(NOW, "today"),
  };
  renderAgenda([overdue, dueToday], transport, workSv);
  const { dates } = await openMenu(dueToday.title, workSv);
  expect(
    dates.getAllByRole("button").map((button) => button.textContent),
  ).toEqual([
    workSv.agendaGroup.today,
    workSv.triageTomorrow,
    workSv.triageNextWeek,
  ]);
  const idag = dates.getByRole("button", { name: workSv.agendaGroup.today });
  expect(idag).toHaveAttribute("aria-pressed", "true");
  expect(idag).toHaveClass("sk-chip");
  expect(
    dates.getByRole("button", { name: workSv.triageTomorrow }),
  ).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(idag);
  expect(updateTask).not.toHaveBeenCalled();
  // Another shortcut still moves the date.
  await userEvent.click(
    dates.getByRole("button", { name: workSv.triageTomorrow }),
  );
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
});

it("the × is named in both languages (locale parity)", async () => {
  const { transport } = makeTransport();
  renderAgenda([overdue], transport, workEn);
  await openMenu(overdue.title, workEn);
  expect(
    within(rowOf(overdue.title)).getByRole("button", { name: "Close" }),
  ).toHaveClass("work-agenda-menu-close");
  expect(workSv.closeMenu).toBe("Stäng");
});

it("a Task without a date has Idag as a plain choice and no chosen chip", async () => {
  const { transport } = makeTransport();
  renderAgenda([overdue, todayTask], transport, workSv);
  const { dates } = await openMenu(todayTask.title, workSv);
  expect(
    dates.getByRole("button", { name: workSv.agendaGroup.today }),
  ).toHaveAttribute("aria-pressed", "false");
  expect(dates.getAllByRole("button")).toHaveLength(3);
  expect(dates.queryAllByRole("button", { pressed: true })).toHaveLength(0);
  // The date input is there without a date: an empty value.
  expect(dates.getByLabelText(workSv.rescheduleDate)).toHaveValue("");
});

it("the date choices in a row's quick choices wrap onto more lines instead of overlapping, under the title", () => {
  // jsdom applies no CSS, so the layout is read from agenda.css. The old triage button grid is gone: the moves sit in
  // the quick choices (.work-agenda-choices), which wrap, and the menu stands under the title's x (the lead column,
  // then the 2 px gap), so the choices never overlap the glyph or the title.
  const css = readFileSync(
    path.resolve(import.meta.dirname, "../src/features/work-app/agenda.css"),
    "utf8",
  );
  expect(css).not.toMatch(/\.work-agenda-triage/);
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-choices \{[^}]*flex-wrap: wrap;/,
  );
  // The menu's surface is its own box, 12 inside it; its chips start on the title's x (the lead column, then 2 px).
  expect(css).toMatch(
    /\.sidekick-work \.work-agenda-menu \{[^}]*padding: var\(--sk-s2\) var\(--sk-s2\) var\(--sk-s2\)\s+calc\(var\(--sk-lead-w\) \+ var\(--sk-lead-hang\) \+ 2px\);/,
  );
});
