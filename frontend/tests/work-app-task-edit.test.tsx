import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { ownerDayPlus } from "@/features/mcp-apps/ui/due";
import { hierarchyDetailLabelsFor } from "@/features/work-app/hierarchy-detail-labels";
import { workEn } from "@/features/work-app/labels";
import { isCompleteDate } from "@/features/work-app/fields";
import {
  dateInputValue,
  dueAtFromDateInput,
} from "@/features/work-app/task-edit";
import {
  KEY,
  keyOf,
  openEdit,
  rootTask,
  step,
  stepId,
  taskA,
  transport,
} from "./helpers/work-app-fixtures";

/** Opens the Task's status chip, the way a user does. */
async function openStatusChip(user: ReturnType<typeof userEvent.setup>) {
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  await user.click(
    await screen.findByRole("button", {
      name: `${dl.changeStatus}: ${workEn.taskStatus.todo}`,
    }),
  );
}

/** The Stockholm calendar day `days` after today, as the date input shows it. */
function dayAfterToday(days: number): string {
  return ownerDayPlus(new Date(), days);
}

it("saves only the changed Task fields with the current version and a key", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, title: "Ring Anna idag", version: 2 },
  });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ring Anna idag");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(
    await screen.findByRole("heading", { level: 2, name: "Ring Anna idag" }),
  ).toBeInTheDocument();
  expect(updateTask).toHaveBeenCalledTimes(1);
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { title: "Ring Anna idag" },
    expect.stringMatching(KEY),
  );
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: workEn.edit })).toBeNull();
});

it("sends a changed priority as priority and nothing else", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, priority: "high", version: 2 },
  });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const priority = screen.getByLabelText(workEn.priority);
  expect(priority).toHaveValue("normal");
  await user.selectOptions(priority, "high");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { priority: "high" },
    expect.stringMatching(KEY),
  );
});

it("keeps an urgent priority as its own option and does not resend it", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, title: "Ring Anna idag", priority: "urgent", version: 2 },
  });
  const getTask = vi.fn().mockResolvedValue({
    task: { ...taskA, priority: "urgent" },
  });
  const work = transport({ getTask, updateTask });
  render(rootTask(work));
  await openEdit(user);
  expect(screen.getByLabelText(workEn.priority)).toHaveValue("urgent");
  expect(
    screen.getByRole("option", { name: workEn.priorityLevel.urgent }),
  ).toBeInTheDocument();
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ring Anna idag");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { title: "Ring Anna idag" },
    expect.stringMatching(KEY),
  );
});

it("sends a changed status from the status chip's menu and nothing else", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, status: "blocked", version: 2 },
  });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openStatusChip(user);
  await user.click(
    within(await screen.findByRole("group", { name: workEn.status })).getByRole(
      "button",
      { name: workEn.taskStatus.blocked },
    ),
  );
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { status: "blocked" },
    expect.stringMatching(KEY),
  );
  expect(screen.queryByLabelText(workEn.titleLabel)).toBeNull();
  // The menu closes.
  expect(screen.queryByRole("group", { name: workEn.status })).toBeNull();
});

it("choosing the current status writes nothing and closes the menu", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn();
  const work = transport({ updateTask });
  render(rootTask(work));
  await openStatusChip(user);
  await user.click(
    within(await screen.findByRole("group", { name: workEn.status })).getByRole(
      "button",
      { name: workEn.taskStatus.todo },
    ),
  );
  expect(screen.queryByRole("group", { name: workEn.status })).toBeNull();
  expect(updateTask).not.toHaveBeenCalled();
});

it("sends a cleared due date as null and nothing else", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, due_at: null, version: 2 },
  });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  await user.click(screen.getByRole("button", { name: workEn.clearDue }));
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { due_at: null },
    expect.stringMatching(KEY),
  );
});

it("shows the Task description, and Show more opens the whole text", async () => {
  const user = userEvent.setup();
  const description =
    "Fakturan ska innehålla timmar för oktober, uppdelade per kund och med momsen angiven för varje rad.";
  const work = transport({
    getTask: vi.fn().mockResolvedValue({ task: { ...taskA, description } }),
  });
  render(rootTask(work));
  expect(await screen.findByText(description)).toHaveClass(
    "work-description-clamped",
  );
  // "Show more" is a tertiary text button right after the text it opens, with no › (› says a row opens a
  // view; this one opens the text in place), not a bold heading-like button.
  const more = screen.getByRole("button", { name: workEn.descriptionMore });
  expect(more).toHaveClass(
    "sk-btn--quiet",
    "sk-btn--compact",
    "work-more-link",
  );
  expect(more).not.toHaveClass("work-text-btn");
  expect(more.querySelector("svg")).toBeNull();
  await user.click(more);
  expect(screen.getByText(description)).not.toHaveClass(
    "work-description-clamped",
  );
  // Open, the button says Show less, also without a glyph.
  expect(
    screen
      .getByRole("button", { name: workEn.descriptionLess })
      .querySelector("svg"),
  ).toBeNull();
  await user.click(
    screen.getByRole("button", { name: workEn.descriptionLess }),
  );
  expect(screen.getByText(description)).toHaveClass("work-description-clamped");
});

it("sends a changed description and an emptied one as null", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, description: "Ny text", version: 2 },
  });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  await user.type(screen.getByLabelText(workEn.description), "Ny text");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { description: "Ny text" },
    expect.stringMatching(KEY),
  );
});

it("clears an existing description with null", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, description: null, version: 2 },
  });
  const work = transport({
    getTask: vi
      .fn()
      .mockResolvedValue({ task: { ...taskA, description: "Gammal text" } }),
    updateTask,
  });
  render(rootTask(work));
  await openEdit(user);
  await user.clear(screen.getByLabelText(workEn.description));
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { description: null },
    expect.stringMatching(KEY),
  );
});

it("sets the due date from the Tomorrow shortcut and saves it as that day", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, version: 2 },
  });
  const work = transport({
    getTask: vi.fn().mockResolvedValue({ task: { ...taskA, due_at: null } }),
    updateTask,
  });
  render(rootTask(work));
  await openEdit(user);
  await user.click(screen.getByRole("button", { name: workEn.dueTomorrow }));
  const tomorrow = dayAfterToday(1);
  expect(screen.getByLabelText(workEn.due)).toHaveValue(tomorrow);
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { due_at: dueAtFromDateInput(tomorrow) },
    expect.stringMatching(KEY),
  );
});

it("the Next week shortcut picks a Monday after today", async () => {
  const user = userEvent.setup();
  const work = transport({
    getTask: vi.fn().mockResolvedValue({ task: { ...taskA, due_at: null } }),
  });
  render(rootTask(work));
  await openEdit(user);
  await user.click(screen.getByRole("button", { name: workEn.dueNextWeek }));
  const value = screen.getByLabelText<HTMLInputElement>(workEn.due).value;
  expect(value).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(new Date(`${value}T12:00:00`).getDay()).toBe(1);
  expect(value > dayAfterToday(0)).toBe(true);
});

it("the No date shortcut clears the due date and sends null", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockResolvedValue({
    task: { ...taskA, due_at: null, version: 2 },
  });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  await user.click(screen.getByRole("button", { name: workEn.dueNone }));
  expect(screen.getByLabelText(workEn.due)).toHaveValue("");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { due_at: null },
    expect.stringMatching(KEY),
  );
});

it("validates the title on the client and sends nothing when it is empty", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn();
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(screen.getByText(workEn.titleRequired)).toBeInTheDocument();
  expect(title).toHaveAttribute("aria-invalid", "true");
  expect(updateTask).not.toHaveBeenCalled();
});

it("shows a conflict banner, reloads the latest version and keeps the typed values", async () => {
  const user = userEvent.setup();
  const latest = { ...taskA, title: "Ring Anna (annan)", version: 2 };
  const getTask = vi
    .fn()
    .mockResolvedValueOnce({ task: taskA })
    .mockResolvedValue({ task: latest });
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({
      task: { ...latest, title: "Ring Anna idag", version: 3 },
    });
  const work = transport({ getTask, updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ring Anna idag");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.conflict);
  expect(banner).toHaveFocus();
  await user.click(within(banner).getByRole("button", { name: workEn.reload }));
  await waitFor(() => expect(getTask).toHaveBeenCalledTimes(2));
  expect(getTask).toHaveBeenLastCalledWith(taskA.id);
  expect(
    await screen.findByRole("heading", { level: 2, name: latest.title }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText(workEn.titleLabel)).toHaveValue(
    "Ring Anna idag",
  );
  expect(screen.queryByRole("alert")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateTask).toHaveBeenCalledTimes(2);
  expect(updateTask.mock.calls[0]).toEqual([
    taskA.id,
    1,
    { title: "Ring Anna idag" },
    expect.stringMatching(KEY),
  ]);
  expect(updateTask.mock.calls[1]).toEqual([
    taskA.id,
    2,
    { title: "Ring Anna idag" },
    expect.stringMatching(KEY),
  ]);
  expect(keyOf(updateTask, 1)).not.toBe(keyOf(updateTask, 0));
});

it("keeps an untouched field at the latest value after a reload", async () => {
  const user = userEvent.setup();
  const latest = { ...taskA, status: "blocked", version: 2 };
  const getTask = vi
    .fn()
    .mockResolvedValueOnce({ task: taskA })
    .mockResolvedValue({ task: latest });
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({ task: { ...latest, title: "Ny", version: 3 } });
  const work = transport({ getTask, updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await user.click(
    within(await screen.findByRole("alert")).getByRole("button", {
      name: workEn.reload,
    }),
  );
  await waitFor(() => expect(getTask).toHaveBeenCalledTimes(2));
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  expect(updateTask.mock.calls[1]).toEqual([
    taskA.id,
    2,
    { title: "Ny" },
    expect.stringMatching(KEY),
  ]);
});

it("shows calm text without retry when the Task write is forbidden", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn().mockRejectedValue(new HostToolError("forbidden"));
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.forbiddenWrite)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
  expect(updateTask).toHaveBeenCalledTimes(1);
});

it("retries a failed save with the same key and the same changes", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
    .mockResolvedValue({ task: { ...taskA, title: "Ny", version: 2 } });
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByRole("alert")).toHaveTextContent(workEn.saveFailed);
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateTask).toHaveBeenCalledTimes(2);
  expect(updateTask.mock.calls[1]).toEqual(updateTask.mock.calls[0]);
});

it("sends one save request for a double-clicked save while the first is pending", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny");
  await user.dblClick(screen.getByRole("button", { name: workEn.save }));
  expect(updateTask).toHaveBeenCalledTimes(1);
});

it("sends only the fields that differ from the Task the user last saw", async () => {
  const user = userEvent.setup();
  const latest = {
    ...taskA,
    title: "Ring Anna (annan)",
    status: "completed",
    version: 2,
  };
  const getTask = vi
    .fn()
    .mockResolvedValueOnce({ task: taskA })
    .mockResolvedValue({ task: latest });
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({
      task: { ...latest, title: "Ring Anna idag", version: 3 },
    });
  const work = transport({ getTask, updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ring Anna idag");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await user.click(
    within(await screen.findByRole("alert")).getByRole("button", {
      name: workEn.reload,
    }),
  );
  await waitFor(() => expect(getTask).toHaveBeenCalledTimes(2));
  // The latest Task is done, so Återöppna stands in place of the status chips, and it stays off while the
  // editor is open.
  expect(
    screen.getByRole("button", { name: workEn.reopenTask }),
  ).toBeDisabled();
  expect(screen.queryByRole("group", { name: workEn.status })).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
  expect(updateTask.mock.calls[0]).toEqual([
    taskA.id,
    1,
    { title: "Ring Anna idag" },
    expect.stringMatching(KEY),
  ]);
  expect(updateTask.mock.calls[1]).toEqual([
    taskA.id,
    2,
    { title: "Ring Anna idag" },
    expect.stringMatching(KEY),
  ]);
});

it("blocks Save with a short text while the date is an incomplete entry", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn();
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const due = screen.getByLabelText(workEn.due);
  Object.defineProperty(due, "validity", {
    value: { badInput: true },
    configurable: true,
  });
  fireEvent.change(due, { target: { value: "" } });
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(screen.getByText(workEn.dueIncomplete)).toBeInTheDocument();
  expect(updateTask).not.toHaveBeenCalled();
});

it("shows a fixed text without retry when the server refuses the values", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockRejectedValue(new HostToolError("validation_error"));
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.invalidChange)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
  expect(updateTask).toHaveBeenCalledTimes(1);
});

it("sends one save request for two save clicks dispatched before React re-renders", async () => {
  const user = userEvent.setup();
  const updateTask = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({ updateTask });
  render(rootTask(work));
  await openEdit(user);
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny");
  const save = screen.getByRole("button", { name: workEn.save });
  act(() => {
    fireEvent.click(save);
    fireEvent.click(save);
  });
  expect(updateTask).toHaveBeenCalledTimes(1);
});

it("sends one step request for two clicks dispatched before React re-renders", async () => {
  const complete = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: [step], next_cursor: null }),
    completeTaskStep: complete,
  });
  render(rootTask(work));
  const checkbox = await screen.findByRole("checkbox", { name: step.title });
  act(() => {
    fireEvent.click(checkbox);
    fireEvent.click(checkbox);
  });
  expect(complete).toHaveBeenCalledTimes(1);
});

it("shows a step conflict banner, disables steps until the re-read arrives, then writes with the new version and key", async () => {
  const user = userEvent.setup();
  const latest = { ...step, version: 4 };
  let resolveRead!: (value: unknown) => void;
  const list = vi
    .fn()
    .mockResolvedValueOnce({ items: [step], next_cursor: null })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveRead = resolve;
        }),
    );
  const complete = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({
      step: { ...latest, status: "completed", version: 5 },
    });
  const work = transport({ listTaskSteps: list, completeTaskStep: complete });
  render(rootTask(work));
  await user.click(await screen.findByRole("checkbox", { name: step.title }));
  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.stepConflict);
  expect(banner).toHaveFocus();
  await user.click(within(banner).getByRole("button", { name: workEn.reload }));
  const checkbox = await screen.findByRole("checkbox", { name: step.title });
  await waitFor(() => expect(checkbox).toBeDisabled());
  act(() => {
    resolveRead({ items: [latest], next_cursor: null });
  });
  await waitFor(() => expect(checkbox).toBeEnabled());
  expect(list).toHaveBeenCalledTimes(2);
  await user.click(checkbox);
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(2));
  expect(complete.mock.calls[0]).toEqual([
    stepId,
    3,
    expect.stringMatching(KEY),
  ]);
  expect(complete.mock.calls[1]).toEqual([
    stepId,
    4,
    expect.stringMatching(KEY),
  ]);
  expect(keyOf(complete, 1)).not.toBe(keyOf(complete, 0));
});

it("maps a due date to 23:59 on its Stockholm day, an empty date to null, and reads the same day back", () => {
  expect(dueAtFromDateInput("2026-11-02")).toBe("2026-11-02T22:59:00.000Z");
  expect(dueAtFromDateInput("2026-07-02")).toBe("2026-07-02T21:59:00.000Z");
  expect(dueAtFromDateInput("")).toBeNull();
  expect(dateInputValue("2026-11-02T22:59:00.000Z")).toBe("2026-11-02");
  expect(dateInputValue(null)).toBe("");
  expect(dateInputValue("not a date")).toBe("");
  expect(dateInputValue(dueAtFromDateInput("2026-11-02"))).toBe("2026-11-02");
  expect(isCompleteDate("2026-11-02")).toBe(true);
  expect(isCompleteDate("0005-01-01")).toBe(false);
  expect(isCompleteDate("2026-02-30")).toBe(false);
  expect(isCompleteDate("2026-1")).toBe(false);
});
