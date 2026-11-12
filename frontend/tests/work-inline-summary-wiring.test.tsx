import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn } from "@/features/work-app/shared/labels";
import { inlineSummaryLabelsEn } from "@/features/work-app/inline/inline-summary-labels";
import type {
  WorkFrame,
  WorkItemRecord,
  WorkProject,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { readStylesheet } from "./helpers/stylesheet";

const task: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Ring Anna om offerten",
  status: "in_progress",
  due_at: null,
  version: 1,
};
const project: WorkProject = {
  id: "019f0000-0000-7000-8000-0000000000f2",
  title: "Offert till Anna",
  status: "active",
  description: null,
  start_date: null,
  target_date: null,
  version: 1,
};

/** The root frames are created once, as sidekick-entry keeps the tool result's frame between renders. */
const taskRoot: WorkFrame = { kind: "task", id: task.id };
const projectRoot: WorkFrame = { kind: "project", id: project.id };

/** Only the reads the Task and Project frames make on open are answered; no write is reached. */
function workWith(): WorkTransport {
  return {
    getTask: vi.fn().mockResolvedValue({ task }),
    getProject: vi.fn().mockResolvedValue({ project }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listProjectTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as WorkTransport;
}

const roots = [
  {
    kind: "task",
    frame: taskRoot,
    title: task.title,
    read: "getTask",
    id: task.id,
    kindLabel: inlineSummaryLabelsEn.kind.task,
    /** A Task with Done: Open is the secondary "Show more" beside it. */
    open: inlineSummaryLabelsEn.showMore,
  },
  {
    kind: "project",
    frame: projectRoot,
    title: project.title,
    read: "getProject",
    id: project.id,
    kindLabel: inlineSummaryLabelsEn.kind.project,
    open: inlineSummaryLabelsEn.showProject,
  },
] as const;

it.each(roots)(
  "shows a root $kind as an inline summary when fullscreen is offered",
  async ({ frame, title, read, id, kindLabel, open }) => {
    const work = workWith();
    render(
      <WorkView
        transport={work}
        initial={frame}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );
    expect(
      await screen.findByRole("region", { name: kindLabel }),
    ).toBeInTheDocument();
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: open })).toBeVisible();
    // The full view is not rendered inline: no level-2 heading with the record's title.
    expect(screen.queryByRole("heading", { level: 2, name: title })).toBeNull();
    expect(work[read]).toHaveBeenCalledWith(id);
  },
);

it.each(roots)(
  "shows the full $kind view when the host cannot show fullscreen",
  async ({ frame, title, read, id, open }) => {
    const work = workWith();
    render(
      <WorkView
        transport={work}
        initial={frame}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={undefined}
      />,
    );
    expect(
      await screen.findByRole("heading", { level: 2, name: title }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: open })).toBeNull();
    expect(work[read]).toHaveBeenCalledWith(id);
  },
);

it.each(roots)(
  "requests fullscreen from Open, shows the full $kind view when the host switches, and returns to the summary inline",
  async ({ frame, title, read, id, open }) => {
    const user = userEvent.setup();
    const work = workWith();
    const fullscreen = vi.fn();
    const { rerender } = render(
      <WorkView
        transport={work}
        initial={frame}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={fullscreen}
      />,
    );
    await user.click(await screen.findByRole("button", { name: open }));
    expect(fullscreen).toHaveBeenCalledTimes(1);

    // The host goes fullscreen: the full view replaces the summary, without a new app start.
    rerender(
      <WorkView
        transport={work}
        initial={frame}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
      />,
    );
    expect(
      await screen.findByRole("heading", { level: 2, name: title }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: open })).toBeNull();
    expect(work[read]).toHaveBeenLastCalledWith(id);

    // The host leaves fullscreen again: the same root returns to the inline summary.
    rerender(
      <WorkView
        transport={work}
        initial={frame}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={fullscreen}
      />,
    );
    expect(await screen.findByRole("button", { name: open })).toBeVisible();
    expect(screen.queryByRole("heading", { level: 2, name: title })).toBeNull();
  },
);

function writeError(code?: string): Error {
  return Object.assign(new Error("write failed"), code ? { code } : {});
}

/** A Task root whose frame carries the record, so the summary shows it with its version at once. */
const taskWithRecord: WorkFrame = { kind: "task", id: task.id, task };

function renderTask(work: WorkTransport) {
  const announce = vi.fn();
  render(
    <WorkView
      transport={work}
      initial={taskWithRecord}
      labels={workEn}
      inlineLabels={inlineSummaryLabelsEn}
      fullscreen={vi.fn()}
      onModelContext={announce}
    />,
  );
  return announce;
}

it("marks a Task done from the inline summary against the version it shows, with no read first", async () => {
  const user = userEvent.setup();
  const work = workWith();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...task, status: "completed", version: 2 } });
  work.updateTask = updateTask;
  const announce = renderTask(work);

  const done = await screen.findByRole("button", {
    name: inlineSummaryLabelsEn.complete,
  });
  // The 44 px minimum is the stylesheet's, not an inline style. jsdom loads no CSS, so the rule is read here.
  expect(done).not.toHaveAttribute("style");
  expect(done).toHaveClass("work-compact-action");
  expect(
    readStylesheet("features/work-app/inline/inline-summary.css").styleOf(
      done,
      {
        room: "sidekick-work",
      },
    )["min-height"],
  ).toBe("var(--sk-tap)");
  await user.click(done);

  expect(work.getTask).not.toHaveBeenCalled();
  expect(updateTask).toHaveBeenCalledWith(
    task.id,
    1,
    { status: "completed" },
    expect.any(String),
  );
  expect(
    await screen.findByText(inlineSummaryLabelsEn.taskStatus.completed),
  ).toBeInTheDocument();
  // A finished Task offers no Done button; the host model hears it was saved.
  expect(
    screen.queryByRole("button", { name: inlineSummaryLabelsEn.complete }),
  ).toBeNull();
  expect(announce).toHaveBeenCalledWith(inlineSummaryLabelsEn.completedNote);
});

it("offers Read again after a version conflict, then writes against the version it read", async () => {
  const user = userEvent.setup();
  const work = workWith();
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(writeError("conflict"))
    .mockResolvedValue({ task: { ...task, status: "completed", version: 4 } });
  work.updateTask = updateTask;
  work.getTask = vi.fn().mockResolvedValue({ task: { ...task, version: 3 } });
  renderTask(work);

  await user.click(
    await screen.findByRole("button", { name: inlineSummaryLabelsEn.complete }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    inlineSummaryLabelsEn.conflict,
  );
  await user.click(
    screen.getByRole("button", { name: inlineSummaryLabelsEn.reread }),
  );
  await user.click(
    await screen.findByRole("button", { name: inlineSummaryLabelsEn.complete }),
  );

  expect(work.getTask).toHaveBeenCalledWith(task.id);
  expect(updateTask).toHaveBeenLastCalledWith(
    task.id,
    3,
    { status: "completed" },
    expect.any(String),
  );
});

it("retries a network failure with the same idempotency key", async () => {
  const user = userEvent.setup();
  const work = workWith();
  const updateTask = vi
    .fn()
    .mockRejectedValueOnce(writeError())
    .mockResolvedValue({ task: { ...task, status: "completed", version: 2 } });
  work.updateTask = updateTask;
  renderTask(work);

  await user.click(
    await screen.findByRole("button", { name: inlineSummaryLabelsEn.complete }),
  );
  await user.click(
    await screen.findByRole("button", { name: inlineSummaryLabelsEn.retry }),
  );

  expect(updateTask).toHaveBeenCalledTimes(2);
  expect(updateTask.mock.calls[1]?.[3]).toBe(updateTask.mock.calls[0]?.[3]);
});

it("shows no Done button on a Project summary", async () => {
  render(
    <WorkView
      transport={workWith()}
      initial={projectRoot}
      labels={workEn}
      inlineLabels={inlineSummaryLabelsEn}
      fullscreen={vi.fn()}
    />,
  );
  await screen.findByRole("region", {
    name: inlineSummaryLabelsEn.kind.project,
  });
  expect(
    screen.queryByRole("button", { name: inlineSummaryLabelsEn.complete }),
  ).toBeNull();
});

/**
 * An agenda root whose page carries the Task, so the rows show it with its version at once. The first
 * overdue record is listed first, and the Task (due today) follows it as a row.
 */
const agendaRoot: WorkFrame = {
  kind: "agenda",
  filters: {},
  page: {
    items: [
      {
        kind: "task",
        id: "019f0000-0000-7000-8000-0000000000f4",
        title: "Betala faktura",
        status: "todo",
        due_at: "2026-10-20T09:00:00Z",
        agenda_group: "overdue",
      } satisfies WorkItemRecord,
      {
        kind: "task",
        id: task.id,
        title: task.title,
        status: "in_progress",
        due_at: null,
        version: 1,
        agenda_group: "today",
      } satisfies WorkItemRecord,
    ],
    next_cursor: null,
  },
};

it("writes nothing from the inline agenda: no update_task call, and a row press asks for fullscreen", async () => {
  const user = userEvent.setup();
  const work = workWith();
  const updateTask = vi.fn();
  work.updateTask = updateTask;
  const fullscreen = vi.fn();
  render(
    <WorkView
      transport={work}
      initial={agendaRoot}
      labels={workEn}
      inlineLabels={inlineSummaryLabelsEn}
      fullscreen={fullscreen}
    />,
  );

  // A row has no status glyph: the row itself is its only button, and pressing it asks for fullscreen.
  expect(document.querySelector(".work-agenda-glyph")).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.agendaUndo })).toBeNull();
  // The inline agenda reads no Task of its own before the press.
  expect(work.getTask).not.toHaveBeenCalled();
  // The row's name is its title and its meta: the status of an in-progress Task.
  await user.click(
    await screen.findByRole("button", {
      name: `${task.title}, In progress`,
    }),
  );
  expect(fullscreen).toHaveBeenCalledTimes(1);
  expect(updateTask).not.toHaveBeenCalled();
  // The press opens the Task in fullscreen, whose own view reads it; the inline row wrote nothing.
  expect(work.getTask).toHaveBeenCalledWith(task.id);
});

it("maps the Project title and Step counts of get_task onto the Task's inline card", async () => {
  const work = workWith();
  work.getTask = vi.fn().mockResolvedValue({
    task: {
      ...task,
      project_title: "Trädgården",
      steps_done: 2,
      steps_total: 4,
    },
  });
  render(
    <WorkView
      transport={work}
      initial={taskRoot}
      labels={workEn}
      inlineLabels={inlineSummaryLabelsEn}
      fullscreen={vi.fn()}
    />,
  );
  const card = await screen.findByRole("region", {
    name: inlineSummaryLabelsEn.kind.task,
  });
  expect(card).toHaveTextContent("Trädgården");
  expect(screen.getByText("2 of 4 steps")).toBeInTheDocument();
});

it("maps the Task counts of get_project onto the Project's inline card", async () => {
  const work = workWith();
  work.getProject = vi.fn().mockResolvedValue({
    project: { ...project, tasks_done: 3, tasks_total: 12, tasks_overdue: 2 },
  });
  render(
    <WorkView
      transport={work}
      initial={projectRoot}
      labels={workEn}
      inlineLabels={inlineSummaryLabelsEn}
      fullscreen={vi.fn()}
    />,
  );
  await screen.findByRole("region", {
    name: inlineSummaryLabelsEn.kind.project,
  });
  expect(screen.getByText("3 of 12 tasks done")).toBeInTheDocument();
  expect(screen.getByText("2 overdue")).toBeInTheDocument();
});
