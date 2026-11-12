import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { openLinkedRowMenu } from "./linked-row-menu-helpers";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { workDate } from "@/features/mcp-apps/ui/due";
import { workEn } from "@/features/work-app/labels";
import { linksLabelsEn } from "@/features/work-app/links-labels";
import { taskPlaceLabelsEn } from "@/features/work-app/task-place-labels";
import { manageLabelsEn } from "@/features/work-app/manage-labels";
import { dueAtFromDateInput } from "@/features/work-app/task-edit";
import { type WorkContact } from "@/features/work-app/transport";
import {
  KEY,
  anna,
  keyOf,
  newStep,
  newTask,
  projectA,
  projectTask,
  rootProject,
  rootTask,
  step,
  taskA,
  transport,
} from "./helpers/work-app-fixtures";

/** Not linked to taskA, so it can be chosen in a search; anna is linked and must not be offered. */
const carl: WorkContact = {
  id: "019f0000-0000-7000-8000-0000000000c3",
  display_name: "Carl Nilsson",
};

/** Opens the quiet "+ New task" line of a Project, which shows the Task form. */
async function openTaskForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: workEn.newTask }));
}

/** Opens the quiet "+ Link contact" line of a Task, which shows the search field. */
async function openContactForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: workEn.linkContact }),
  );
}

/** Opens the quiet "+ Add step" line of a Task, which shows the Step form. */
async function openStepForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: workEn.addStep }));
}

it("opens a Task's Project and a Task of the Project, and goes back one step at a time", async () => {
  const user = userEvent.setup();
  const work = transport({
    getWorkHierarchy: vi
      .fn()
      .mockResolvedValue({ kind: "hierarchy", nodes: [], truncated: false }),
    getTask: vi.fn((id: string) =>
      Promise.resolve({
        task: { ...projectTask, project_title: projectA.title, id },
      }),
    ),
  });
  render(rootTask(work, projectTask.id));
  // The place chip names the Project; its panel links to the Project page.
  await user.click(
    await screen.findByRole("button", {
      name: `Change place: ${projectA.title}`,
    }),
  );
  await user.click(
    await screen.findByRole("button", { name: `Open ${projectA.title}` }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: projectA.title }),
  ).toHaveFocus();
  expect(work.getProject).toHaveBeenCalledWith(projectA.id);
  await user.click(
    await screen.findByRole("button", { name: projectTask.title }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: projectTask.title }),
  ).toBeInTheDocument();
  expect(work.getTask).toHaveBeenLastCalledWith(projectTask.id);
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("heading", { level: 2, name: projectA.title }),
  ).toBeInTheDocument();
  expect(work.listProjectTasks).toHaveBeenCalledWith(projectA.id);
  await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
  expect(
    await screen.findByRole("heading", { level: 2, name: projectTask.title }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Tillbaka till / })).toBeNull();
});

it("names the Project with its plain label in the place chip when the Task carries no title", async () => {
  const work = transport({
    getProject: vi.fn().mockRejectedValue(new Error("PRIVATE_BACKEND_MESSAGE")),
  });
  render(rootTask(work, projectTask.id));
  expect(
    await screen.findByRole("button", {
      name: `Change place: ${taskPlaceLabelsEn.projectName}`,
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 2, name: projectTask.title }),
  ).toBeInTheDocument();
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("shows the Project's dates as the calendar days they name and its description", async () => {
  const work = transport();
  render(rootProject(work));
  expect(
    await screen.findByText(projectA.description as string),
  ).toBeInTheDocument();
  expect(
    screen.getByText(workDate("2026-10-01", new Date(), "en-GB")),
  ).toBeInTheDocument();
  expect(
    screen.getByText(workDate("2026-11-15", new Date(), "en-GB")),
  ).toBeInTheDocument();
  expect(work.listProjectTasks).toHaveBeenCalledWith(projectA.id);
});

it("saves only the changed Project fields, with dates as YYYY-MM-DD", async () => {
  const user = userEvent.setup();
  const updateProject = vi.fn().mockResolvedValue({
    project: {
      ...projectA,
      title: "Ny titel",
      status: "paused",
      start_date: "2026-10-05",
      target_date: null,
      version: 2,
    },
  });
  const work = transport({ updateProject });
  render(rootProject(work));
  await user.click(await screen.findByRole("button", { name: workEn.edit }));
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Ny titel");
  await user.selectOptions(screen.getByLabelText(workEn.status), "paused");
  fireEvent.change(screen.getByLabelText(workEn.startDate), {
    target: { value: "2026-10-05" },
  });
  await user.click(
    screen.getByRole("button", { name: workEn.clearTargetDate }),
  );
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateProject).toHaveBeenCalledTimes(1);
  expect(updateProject).toHaveBeenCalledWith(
    projectA.id,
    1,
    {
      title: "Ny titel",
      status: "paused",
      start_date: "2026-10-05",
      target_date: null,
    },
    expect.stringMatching(KEY),
  );
  expect(screen.queryByRole("form", { name: workEn.edit })).toBeNull();
});

it("sends a cleared description as null and an untouched Project as no write", async () => {
  const user = userEvent.setup();
  const updateProject = vi.fn().mockResolvedValue({
    project: { ...projectA, description: null, version: 2 },
  });
  const work = transport({ updateProject });
  render(rootProject(work));
  await user.click(await screen.findByRole("button", { name: workEn.edit }));
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(updateProject).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: workEn.edit }));
  await user.clear(screen.getByLabelText(workEn.description));
  await user.click(screen.getByRole("button", { name: workEn.save }));
  await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(1));
  expect(updateProject).toHaveBeenCalledWith(
    projectA.id,
    1,
    { description: null },
    expect.stringMatching(KEY),
  );
});

it("blocks Save of a Project while a date is an incomplete entry", async () => {
  const user = userEvent.setup();
  const updateProject = vi.fn();
  const work = transport({ updateProject });
  render(rootProject(work));
  await user.click(await screen.findByRole("button", { name: workEn.edit }));
  const start = screen.getByLabelText(workEn.startDate);
  Object.defineProperty(start, "validity", {
    value: { badInput: true },
    configurable: true,
  });
  fireEvent.change(start, { target: { value: "" } });
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(screen.getByText(workEn.dateIncomplete)).toBeInTheDocument();
  expect(start).toHaveAttribute("aria-invalid", "true");
  expect(updateProject).not.toHaveBeenCalled();
});

it("shows a conflict banner for a Project, reloads the latest version and keeps the typed values", async () => {
  const user = userEvent.setup();
  const latest = { ...projectA, title: "Offert (annan)", version: 2 };
  const getProject = vi
    .fn()
    .mockResolvedValueOnce({ project: projectA })
    .mockResolvedValue({ project: latest });
  const updateProject = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({
      project: { ...latest, title: "Offert idag", version: 3 },
    });
  const work = transport({ getProject, updateProject });
  render(rootProject(work));
  await user.click(await screen.findByRole("button", { name: workEn.edit }));
  const title = screen.getByLabelText(workEn.titleLabel);
  await user.clear(title);
  await user.type(title, "Offert idag");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.projectConflict);
  expect(banner).toHaveFocus();
  await user.click(within(banner).getByRole("button", { name: workEn.reload }));
  expect(
    await screen.findByRole("heading", { level: 2, name: latest.title }),
  ).toBeInTheDocument();
  expect(getProject).toHaveBeenLastCalledWith(projectA.id);
  expect(screen.getByLabelText(workEn.titleLabel)).toHaveValue("Offert idag");
  expect(screen.queryByRole("alert")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateProject).toHaveBeenCalledTimes(2);
  expect(updateProject.mock.calls[0]).toEqual([
    projectA.id,
    1,
    { title: "Offert idag" },
    expect.stringMatching(KEY),
  ]);
  expect(updateProject.mock.calls[1]).toEqual([
    projectA.id,
    2,
    { title: "Offert idag" },
    expect.stringMatching(KEY),
  ]);
  expect(keyOf(updateProject, 1)).not.toBe(keyOf(updateProject, 0));
});

it("shows an empty state for a Project without tasks and a calm notice when its tasks are forbidden", async () => {
  const empty = transport({
    listProjectTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  });
  const { unmount } = render(rootProject(empty));
  expect(await screen.findByText(workEn.noProjectTasks)).toBeInTheDocument();
  unmount();
  const forbidden = transport({
    listProjectTasks: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
  });
  render(rootProject(forbidden));
  expect(await screen.findByText(workEn.tasksForbidden)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(
    screen.getByRole("heading", { level: 2, name: projectA.title }),
  ).toBeInTheDocument();
});

it("creates a Task in the Project, reuses its key on retry and lists it at the top", async () => {
  const user = userEvent.setup();
  const create = vi
    .fn()
    .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
    .mockResolvedValue({ task: newTask });
  const work = transport({ createTask: create });
  render(rootProject(work));
  await screen.findByRole("button", { name: projectTask.title });
  await openTaskForm(user);
  await user.type(screen.getByLabelText(workEn.newTaskTitle), newTask.title);
  await user.click(screen.getByRole("button", { name: workEn.createTask }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    workEn.taskCreateFailed,
  );
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("button", { name: newTask.title }),
  ).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(workEn.taskCreated);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByLabelText(workEn.newTaskTitle)).toHaveValue("");
  expect(screen.getAllByRole("listitem")[0]).toHaveTextContent(newTask.title);
  expect(create).toHaveBeenCalledTimes(2);
  const payload = {
    title: newTask.title,
    project_id: projectA.id,
    due_at: null,
  };
  expect(create.mock.calls[0]).toEqual([payload, expect.stringMatching(KEY)]);
  expect(create.mock.calls[1]).toEqual(create.mock.calls[0]);
});

it("sends a due date as 23:59 on its Stockholm day and a new key when the values change", async () => {
  const user = userEvent.setup();
  const create = vi.fn().mockResolvedValue({ task: newTask });
  const work = transport({ createTask: create });
  render(rootProject(work));
  await screen.findByRole("button", { name: projectTask.title });
  await openTaskForm(user);
  await user.type(screen.getByLabelText(workEn.newTaskTitle), "Ring");
  fireEvent.change(screen.getByLabelText(workEn.newTaskDue), {
    target: { value: "2026-11-02" },
  });
  await user.click(screen.getByRole("button", { name: workEn.createTask }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  expect(create.mock.calls[0]?.[0]).toEqual({
    title: "Ring",
    project_id: projectA.id,
    due_at: dueAtFromDateInput("2026-11-02"),
  });
  await user.type(screen.getByLabelText(workEn.newTaskTitle), "Ny");
  await user.click(screen.getByRole("button", { name: workEn.createTask }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
  expect(keyOf(create, 1)).not.toBe(keyOf(create, 0));
});

it("blocks an empty Task title and an incomplete date on the client", async () => {
  const user = userEvent.setup();
  const create = vi.fn().mockResolvedValue({ task: newTask });
  const work = transport({ createTask: create });
  render(rootProject(work));
  await screen.findByRole("button", { name: projectTask.title });
  await openTaskForm(user);
  await user.click(screen.getByRole("button", { name: workEn.createTask }));
  expect(await screen.findByText(workEn.titleRequired)).toBeInTheDocument();
  expect(create).not.toHaveBeenCalled();
  await user.type(screen.getByLabelText(workEn.newTaskTitle), "Ring");
  const due = screen.getByLabelText(workEn.newTaskDue);
  fireEvent.change(due, { target: { value: "2026-11-02" } });
  // A partial entry reads as "" with badInput set; it must block the create, not clear the date.
  Object.defineProperty(due, "validity", {
    value: { badInput: true },
    configurable: true,
  });
  fireEvent.change(due, { target: { value: "" } });
  await user.click(screen.getByRole("button", { name: workEn.createTask }));
  expect(await screen.findByText(workEn.dueIncomplete)).toBeInTheDocument();
  expect(create).not.toHaveBeenCalled();
});

it("sends one create request for a double-clicked Task", async () => {
  const user = userEvent.setup();
  const create = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({ createTask: create });
  render(rootProject(work));
  await screen.findByRole("button", { name: projectTask.title });
  await openTaskForm(user);
  await user.type(screen.getByLabelText(workEn.newTaskTitle), "Ring");
  await user.dblClick(screen.getByRole("button", { name: workEn.createTask }));
  expect(create).toHaveBeenCalledTimes(1);
});

it("adds a Step at the end of the list with its version and checks it at once", async () => {
  const user = userEvent.setup();
  const create = vi.fn().mockResolvedValue({ step: newStep });
  const complete = vi.fn().mockResolvedValue({
    step: { ...newStep, status: "completed", version: 2 },
  });
  const work = transport({
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: [step], next_cursor: null }),
    createTaskStep: create,
    completeTaskStep: complete,
  });
  render(rootTask(work));
  await screen.findByRole("checkbox", { name: step.title });
  await openStepForm(user);
  await user.type(screen.getByLabelText(workEn.stepTitle), newStep.title);
  await user.click(screen.getByRole("button", { name: workEn.addStep }));
  const added = await screen.findByRole("checkbox", { name: newStep.title });
  expect(screen.getByRole("status")).toHaveTextContent(workEn.stepAdded);
  expect(screen.getAllByRole("checkbox").at(-1)).toBe(added);
  expect(create).toHaveBeenCalledWith(
    taskA.id,
    newStep.title,
    expect.stringMatching(KEY),
  );
  await user.click(added);
  await waitFor(() => expect(added).toBeChecked());
  expect(complete).toHaveBeenCalledWith(
    newStep.id,
    1,
    expect.stringMatching(KEY),
  );
});

it("blocks a too long Step title on the client, names the limit under the field and does not send it", async () => {
  const user = userEvent.setup();
  const create = vi.fn().mockResolvedValue({ step: newStep });
  const work = transport({ createTaskStep: create });
  render(rootTask(work));
  await openStepForm(user);
  const field = screen.getByRole("textbox", { name: workEn.stepTitle });
  await user.click(field);
  await user.paste("x".repeat(201));
  await user.keyboard("{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    workEn.titleTooLong,
  );
  expect(create).not.toHaveBeenCalled();
  expect(field).toHaveValue("x".repeat(201));
});

it("keeps the Step key for a retry of the same title and reports a failure calmly", async () => {
  const user = userEvent.setup();
  const create = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("forbidden"))
    .mockResolvedValue({ step: newStep });
  const work = transport({ createTaskStep: create });
  render(rootTask(work));
  await openStepForm(user);
  await user.type(screen.getByLabelText(workEn.stepTitle), newStep.title);
  await user.click(screen.getByRole("button", { name: workEn.addStep }));
  expect(await screen.findByText(workEn.forbiddenWrite)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.addStep }));
  expect(
    await screen.findByRole("checkbox", { name: newStep.title }),
  ).toBeInTheDocument();
  expect(create).toHaveBeenCalledTimes(2);
  expect(create.mock.calls[1]).toEqual(create.mock.calls[0]);
});

it("waits for a pause before searching contacts and never searches a single letter", async () => {
  const user = userEvent.setup();
  const search = vi
    .fn()
    .mockResolvedValue({ items: [carl], next_cursor: null });
  const work = transport({ searchContacts: search });
  render(rootTask(work));
  await openContactForm(user);
  const input = await screen.findByLabelText(workEn.linkContact);
  await user.type(input, "C");
  await new Promise((resolve) => setTimeout(resolve, 400));
  expect(search).not.toHaveBeenCalled();
  await user.type(input, "arl");
  expect(
    await screen.findByRole("button", { name: carl.display_name }),
  ).toBeInTheDocument();
  expect(search).toHaveBeenCalledTimes(1);
  expect(search).toHaveBeenCalledWith("Carl");
});

it("ignores the answer to an older search query and offers no linked contact", async () => {
  const user = userEvent.setup();
  let resolveOld!: (value: unknown) => void;
  const bo: WorkContact = {
    id: "019f0000-0000-7000-8000-0000000000c4",
    display_name: "Bo Berg",
  };
  const search = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue({ items: [carl, anna], next_cursor: null });
  const work = transport({ searchContacts: search });
  render(rootTask(work));
  await openContactForm(user);
  const input = await screen.findByLabelText(workEn.linkContact);
  await user.type(input, "Bo");
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
  await user.clear(input);
  await user.type(input, "Ca");
  expect(
    await screen.findByRole("button", { name: carl.display_name }),
  ).toBeInTheDocument();
  act(() => {
    resolveOld({ items: [bo], next_cursor: null });
  });
  expect(screen.queryByRole("button", { name: bo.display_name })).toBeNull();
  // anna is linked to the Task, so the only button with her name is the contact row.
  expect(
    screen.getAllByRole("button", { name: anna.display_name }),
  ).toHaveLength(1);
});

it("links a searched contact, reads the contact list again and returns focus to Contacts", async () => {
  const user = userEvent.setup();
  const link = vi.fn().mockResolvedValue({ linked: true });
  const list = vi
    .fn()
    .mockResolvedValueOnce({ items: [anna], next_cursor: null })
    .mockResolvedValueOnce({ items: [anna, carl], next_cursor: null });
  const work = transport({
    listTaskContacts: list,
    searchContacts: vi
      .fn()
      .mockResolvedValue({ items: [carl], next_cursor: null }),
    linkContactToTask: link,
  });
  render(rootTask(work));
  await screen.findByRole("button", { name: anna.display_name });
  await openContactForm(user);
  await user.type(screen.getByLabelText(workEn.linkContact), "Carl");
  await user.click(
    await screen.findByRole("button", { name: carl.display_name }),
  );
  await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  expect(link).toHaveBeenCalledWith(
    taskA.id,
    carl.id,
    expect.stringMatching(KEY),
  );
  expect(
    await screen.findByRole("button", { name: carl.display_name }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 3, name: workEn.contacts }),
  ).toHaveFocus();
  // The contact list is read again, which draws the search line anew: it is closed again.
  expect(screen.queryByLabelText(workEn.linkContact)).toBeNull();
  expect(
    screen.getByRole("button", { name: workEn.linkContact }),
  ).toBeInTheDocument();
});

it("sends one link request for a double-clicked search result", async () => {
  const user = userEvent.setup();
  const link = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({
    searchContacts: vi
      .fn()
      .mockResolvedValue({ items: [carl], next_cursor: null }),
    linkContactToTask: link,
  });
  render(rootTask(work));
  await screen.findByRole("button", { name: anna.display_name });
  await openContactForm(user);
  await user.type(screen.getByLabelText(workEn.linkContact), "Carl");
  await user.dblClick(
    await screen.findByRole("button", { name: carl.display_name }),
  );
  expect(link).toHaveBeenCalledTimes(1);
});

it("removes a link at once from the Contact row's own menu, with no confirmation, and keeps the row with Undo without reading the list again", async () => {
  const user = userEvent.setup();
  const unlink = vi.fn().mockResolvedValue({ linked: false });
  const list = vi.fn().mockResolvedValue({ items: [anna], next_cursor: null });
  const work = transport({
    listTaskContacts: list,
    unlinkContactFromTask: unlink,
  });
  render(rootTask(work));
  const row = (
    await screen.findByRole("button", { name: anna.display_name })
  ).closest("li") as HTMLElement;
  await user.click(await openLinkedRowMenu(row));
  // The Undo line reads "Link removed" with the Undo button beside it, in the same wrapper.
  expect(await within(row).findByRole("status")).toHaveTextContent(
    linksLabelsEn.linkRemoved,
  );
  expect(
    within(row).getByRole("button", { name: workEn.agendaUndo }),
  ).toBeInTheDocument();
  expect(
    within(row).getByRole("button", { name: anna.display_name }),
  ).toBeInTheDocument();
  expect(unlink).toHaveBeenCalledTimes(1);
  expect(unlink).toHaveBeenCalledWith(
    taskA.id,
    anna.id,
    expect.stringMatching(KEY),
  );
  expect(list).toHaveBeenCalledTimes(1);
});

it("shows a link conflict as a banner that reads the contact list again", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockResolvedValueOnce({ items: [anna], next_cursor: null })
    .mockResolvedValueOnce({ items: [anna, carl], next_cursor: null })
    .mockResolvedValue({ items: [anna, carl], next_cursor: null });
  const link = vi.fn().mockRejectedValue(new HostToolError("conflict"));
  const work = transport({
    listTaskContacts: list,
    searchContacts: vi
      .fn()
      .mockResolvedValue({ items: [carl], next_cursor: null }),
    linkContactToTask: link,
  });
  render(rootTask(work));
  await screen.findByRole("button", { name: anna.display_name });
  await openContactForm(user);
  await user.type(screen.getByLabelText(workEn.linkContact), "Carl");
  await user.click(
    await screen.findByRole("button", { name: carl.display_name }),
  );
  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.contactConflict);
  expect(banner).toHaveFocus();
  await user.click(within(banner).getByRole("button", { name: workEn.reload }));
  await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("shows a removal that the server refuses as calm text under the list, and the row keeps its link", async () => {
  const user = userEvent.setup();
  const unlink = vi.fn().mockRejectedValue(new HostToolError("forbidden"));
  const work = transport({ unlinkContactFromTask: unlink });
  render(rootTask(work));
  const row = (
    await screen.findByRole("button", { name: anna.display_name })
  ).closest("li") as HTMLElement;
  await user.click(await openLinkedRowMenu(row));
  // The refusal is the shared write notice: the calm line, not the backend's words.
  expect(await screen.findByRole("alert")).toHaveTextContent(
    manageLabelsEn.forbidden,
  );
  expect(within(row).queryByRole("status")).toBeNull();
  expect(
    within(row).queryByRole("button", { name: workEn.agendaUndo }),
  ).toBeNull();
  expect(unlink).toHaveBeenCalledTimes(1);
});

it("opens a Task that was just created in the Project from the top of its list", async () => {
  const user = userEvent.setup();
  const work = transport({
    createTask: vi.fn().mockResolvedValue({ task: newTask }),
    getTask: vi.fn().mockResolvedValue({ task: newTask }),
  });
  render(rootProject(work));
  await screen.findByRole("button", { name: projectTask.title });
  await openTaskForm(user);
  await user.type(screen.getByLabelText(workEn.newTaskTitle), newTask.title);
  await user.click(screen.getByRole("button", { name: workEn.createTask }));
  await user.click(await screen.findByRole("button", { name: newTask.title }));
  expect(
    await screen.findByRole("heading", { level: 2, name: newTask.title }),
  ).toBeInTheDocument();
  expect(work.getTask).toHaveBeenCalledWith(newTask.id);
});

it("sends one unlink request for a double-clicked Remove link", async () => {
  const user = userEvent.setup();
  const unlink = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({ unlinkContactFromTask: unlink });
  render(rootTask(work));
  const row = (
    await screen.findByRole("button", { name: anna.display_name })
  ).closest("li") as HTMLElement;
  await user.dblClick(await openLinkedRowMenu(row));
  expect(unlink).toHaveBeenCalledTimes(1);
});
