import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, onTestFinished, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { hierarchyDetailLabelsEn } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { inlineSummaryLabelsEn } from "@/features/work-app/inline/inline-summary-labels";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

const taskA: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};

/** A transport with only the reads TaskFrame makes on open, plus the update under test. */
function transport(overrides: Partial<WorkTransport> = {}): WorkTransport {
  return {
    getTask: vi.fn().mockResolvedValue({ task: taskA }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    updateTask: vi.fn().mockResolvedValue({
      task: { ...taskA, status: "completed", version: 2 },
    }),
    ...overrides,
  } as unknown as WorkTransport;
}

function renderTask(work: WorkTransport) {
  return render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: taskA.id }}
      labels={workEn}
    />,
  );
}

/** The Task's status chip, once the Task has loaded; its name is "Change status: <current status>". */
function statusChip(): Promise<HTMLElement> {
  return screen.findByRole("button", {
    name: new RegExp(`^${hierarchyDetailLabelsEn.changeStatus}: `),
  });
}

/** Opens the status chip and returns the menu group ("Att göra", "Pågår", "Blockerad"). */
async function openStatusMenu(
  user: ReturnType<typeof userEvent.setup>,
): Promise<HTMLElement> {
  await user.click(await statusChip());
  return screen.getByRole("group", { name: workEn.status });
}

/** Opens the editor the way the user does: ⋯, then "Edit" (the title tap works too). */
async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
  await user.click(screen.getByRole("button", { name: workEn.edit }));
}

/** A status menu entry's label, without the ✓ that marks the stored status. */
function menuLabel(button: HTMLElement): string {
  return (button.textContent ?? "").replace("✓", "").trim();
}

/** The label of the pressed status entry, or undefined when none is pressed. */
function pressedStatus(group: HTMLElement): string | undefined {
  const pressed = within(group)
    .getAllByRole("button")
    .find((entry) => entry.getAttribute("aria-pressed") === "true");
  return pressed ? menuLabel(pressed) : undefined;
}

describe("TaskFrame status", () => {
  it("opens a status menu with the three open statuses, the current one pressed and marked ✓, and no Klar entry", async () => {
    renderTask(transport());

    const user = userEvent.setup();
    const group = await openStatusMenu(user);
    const entries = within(group).getAllByRole("button");
    expect(entries.map(menuLabel)).toEqual([
      workEn.taskStatus.todo,
      workEn.taskStatus.in_progress,
      workEn.taskStatus.blocked,
    ]);
    expect(pressedStatus(group)).toBe(workEn.taskStatus.todo);
    expect(entries[0]).toHaveTextContent("✓");
    expect(entries[1]).not.toHaveTextContent("✓");
    expect(entries[2]).not.toHaveTextContent("✓");
  });

  it("writes the chosen status with the shown version and key, closes the menu and shows the stored status", async () => {
    const work = transport({
      updateTask: vi.fn().mockResolvedValue({
        task: { ...taskA, status: "in_progress", version: 2 },
      }),
    });
    renderTask(work);

    const user = userEvent.setup();
    const group = await openStatusMenu(user);
    await user.click(
      within(group).getByRole("button", {
        name: workEn.taskStatus.in_progress,
      }),
    );

    await waitFor(() =>
      expect(work.updateTask).toHaveBeenCalledWith(
        taskA.id,
        1,
        { status: "in_progress" },
        expect.any(String),
      ),
    );
    expect(
      screen.queryByRole("group", { name: workEn.status }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: `${hierarchyDetailLabelsEn.changeStatus}: ${workEn.taskStatus.in_progress}`,
      }),
    ).toBeVisible();
  });

  it("does not write when the stored status is chosen again, and closes the menu with focus on the chip", async () => {
    const work = transport();
    renderTask(work);

    const user = userEvent.setup();
    const group = await openStatusMenu(user);
    await user.click(
      within(group).getByRole("button", {
        name: workEn.taskStatus.todo,
      }),
    );

    expect(work.updateTask).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("group", { name: workEn.status }),
    ).not.toBeInTheDocument();
    expect(await statusChip()).toHaveFocus();
  });

  it("shows the conflict banner when the Task changed elsewhere and keeps the old status pressed", async () => {
    const work = transport({
      updateTask: vi.fn().mockRejectedValue(new HostToolError("conflict")),
    });
    renderTask(work);

    const user = userEvent.setup();
    const group = await openStatusMenu(user);
    await user.click(
      within(group).getByRole("button", {
        name: workEn.taskStatus.blocked,
      }),
    );

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(workEn.conflict);
    expect(
      within(banner).getByRole("button", { name: workEn.reload }),
    ).toBeVisible();
    expect(pressedStatus(await openStatusMenu(user))).toBe(
      workEn.taskStatus.todo,
    );
  });

  it("is off while the editor is open, so the typed values are not touched", async () => {
    const work = transport();
    renderTask(work);

    const user = userEvent.setup();
    await openEditor(user);

    expect(await statusChip()).toBeDisabled();
    expect(screen.getByRole("button", { name: workEn.addDue })).toBeDisabled();
    expect(work.updateTask).not.toHaveBeenCalled();
    expect(screen.getByLabelText(workEn.titleLabel)).toBeInTheDocument();
  });
});

describe("TaskFrame Markera klar", () => {
  it("sits before the description in the document, last inside the property row, as the screen's one compact primary", async () => {
    const description = "Skicka offerten till kunden före fredag.";
    const work = transport({
      getTask: vi.fn().mockResolvedValue({
        task: { ...taskA, description },
      }),
    });
    renderTask(work);

    const done = await screen.findByRole("button", { name: workEn.markDone });
    const text = await screen.findByText(description);
    // DOCUMENT_POSITION_FOLLOWING: the text comes after the button in the document order.
    expect(
      done.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(done).toHaveClass(
      "sk-btn--primary",
      "sk-btn--compact",
      "work-task-done",
    );
    expect(done).not.toHaveClass("sk-btn--tonal");
    // Inside .work-task-props, after the property chips.
    const props = done.closest(".work-task-props");
    expect(props).not.toBeNull();
    expect(props?.lastElementChild).toBe(done);
    expect(props?.querySelectorAll(".work-prop-chip").length).toBeGreaterThan(
      0,
    );
  });

  it("writes Klar through the status write, with the shown version and key, and shows Ångra in its place", async () => {
    const work = transport();
    renderTask(work);

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );

    await waitFor(() =>
      expect(work.updateTask).toHaveBeenCalledWith(
        taskA.id,
        1,
        { status: "completed" },
        expect.any(String),
      ),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: workEn.markDone }),
      ).not.toBeInTheDocument(),
    );
    // Until the time to undo is up, Ångra stands where Återöppna will.
    expect(
      screen.getByRole("button", { name: workEn.agendaUndo }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: workEn.reopenTask }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: workEn.status }),
    ).not.toBeInTheDocument();
  });

  it("says so when the write fails, in the write error row under the controls, and Try again repeats it with the same key", async () => {
    const work = transport({
      updateTask: vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValueOnce({
          task: { ...taskA, status: "completed", version: 2 },
        }),
    });
    renderTask(work);

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("sk-error--row");
    // The same words as the inline card, and focus on Try again where the press was.
    expect(alert).toHaveTextContent(inlineSummaryLabelsEn.doneFailed);
    expect(screen.getByRole("button", { name: workEn.retry })).toHaveFocus();
    // The family's row: a line and a text button, so the sentence does not say the button's words again.
    expect(inlineSummaryLabelsEn.doneFailed).not.toMatch(/try again/i);
    // It stands with the controls it came from, before the title's description and the other sections.
    expect(
      screen
        .getByRole("button", { name: workEn.markDone })
        .compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: workEn.retry }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: workEn.agendaUndo }),
      ).toBeVisible(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(work.updateTask).toHaveBeenCalledTimes(2);
    expect(vi.mocked(work.updateTask).mock.calls[1]?.[3]).toBe(
      vi.mocked(work.updateTask).mock.calls[0]?.[3],
    );
  });

  it("is not shown for a Task that is already Klar; Återöppna writes Att göra instead", async () => {
    const done = { ...taskA, status: "completed", version: 3 };
    const work = transport({
      getTask: vi.fn().mockResolvedValue({ task: done }),
      updateTask: vi.fn().mockResolvedValue({
        task: { ...done, status: "todo", version: 4 },
      }),
    });
    renderTask(work);

    const reopen = await screen.findByRole("button", {
      name: workEn.reopenTask,
    });
    expect(reopen).toHaveClass(
      "sk-btn--secondary",
      "sk-btn--compact",
      "work-task-done",
    );
    expect(reopen).not.toHaveClass("sk-btn--primary");
    expect(
      screen.queryByRole("button", { name: workEn.markDone }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: workEn.status }),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(reopen);
    await waitFor(() =>
      expect(work.updateTask).toHaveBeenCalledWith(
        taskA.id,
        3,
        { status: "todo" },
        expect.any(String),
      ),
    );
    expect(
      await screen.findByRole("button", { name: workEn.markDone }),
    ).toBeVisible();
  });

  it("is off while the editor is open", async () => {
    renderTask(transport());

    const user = userEvent.setup();
    await openEditor(user);

    expect(
      screen.getByRole("button", { name: workEn.markDone }),
    ).toBeDisabled();
  });
});

/**
 * The date in the date chip under the title, once the Task has loaded. The chip's name starts with the date
 * label; its first span holds the date alone ("fre 30 okt"). How late a Task is stands on its own line.
 */
async function dueLine(labels: WorkLabels = workEn): Promise<HTMLElement> {
  const chip = await screen.findByRole("button", {
    name: new RegExp(`^${labels.changeDue}: `),
  });
  return chip.querySelector<HTMLElement>("span") ?? chip;
}

// Thursday 12 November 2026, 11:00 on the owner's clock (Europe/Stockholm, UTC+1), and the end of the next day there.
const FROZEN_NOW = new Date("2026-11-12T10:00:00.000Z");
const END_OF_TOMORROW = "2026-11-13T22:59:00.000Z";

describe("TaskFrame due date", () => {
  it("puts how late a passed date is on its own line above the chips, and a coming date shows only the date, with no Förföll or Förfaller prefix", async () => {
    const past = new Date(Date.now() - 5 * 86_400_000).toISOString();
    const { unmount } = render(
      <WorkView
        transport={transport({
          getTask: vi
            .fn()
            .mockResolvedValue({ task: { ...taskA, due_at: past } }),
        })}
        initial={{ kind: "task", id: taskA.id }}
        labels={workSv}
      />,
    );
    // How late the Task is stands in the Task's one meta line (p.work-task-meta) between the title and the chips; the
    // chip keeps the date.
    const lateLine = await screen.findByText(/dagar försenad$/);
    expect(lateLine.tagName).toBe("SPAN");
    expect(lateLine.parentElement?.tagName).toBe("P");
    expect(lateLine.parentElement).toHaveClass("work-task-meta");
    expect(lateLine).toHaveClass("work-task-late");
    expect(
      lateLine.parentElement?.querySelector(".work-task-project"),
    ).toBeNull();
    expect(lateLine).toHaveTextContent(/^\d+ dagar försenad$/);
    expect(lateLine).not.toHaveTextContent("Förföll");
    const late = await dueLine(workSv);
    expect(late.textContent?.trim()).toMatch(/^(\S+ )?\d{1,2} \S+$/);
    expect(late).not.toHaveTextContent("försenad");
    unmount();

    const coming = new Date(Date.now() + 10 * 86_400_000).toISOString();
    render(
      <WorkView
        transport={transport({
          getTask: vi
            .fn()
            .mockResolvedValue({ task: { ...taskA, due_at: coming } }),
        })}
        initial={{ kind: "task", id: taskA.id }}
        labels={workSv}
      />,
    );
    // A coming date shows only the date: no distance ("om 10 dagar") and no late line anywhere.
    const due = await dueLine(workSv);
    expect(due).not.toHaveTextContent("Förfaller");
    expect(due.textContent?.trim()).toMatch(/^(\S+ )?\d{1,2} \S+$/);
    expect(screen.queryByText(/om \d+ dagar/)).toBeNull();
    expect(document.querySelector(".work-task-late")).toBeNull();
    expect(document.querySelector(".work-task-meta")).toBeNull();
    expect(due).not.toHaveTextContent("försenad");
    expect(
      screen.getByRole("button", {
        name: new RegExp(`^${workSv.changeDue}: `),
      }),
    ).toBeVisible();
  });

  it("keeps only how late it is on the meta line; the project is the place chip's name", async () => {
    const past = new Date(Date.now() - 5 * 86_400_000).toISOString();
    const { unmount } = render(
      <WorkView
        transport={transport({
          getTask: vi.fn().mockResolvedValue({
            task: {
              ...taskA,
              due_at: past,
              project_id: "p-1",
              project_title: "Kök",
            },
          }),
        })}
        initial={{ kind: "task", id: taskA.id }}
        labels={workSv}
      />,
    );
    const late = await screen.findByText(/dagar försenad$/);
    const meta = late.parentElement as HTMLElement;
    expect(meta).toHaveClass("work-task-meta");
    expect(Array.from(meta.children, (child) => child.className)).toEqual([
      "work-task-late",
    ]);
    expect(
      screen.getByRole("button", { name: "Ändra plats: Kök" }),
    ).toHaveTextContent("Plats: Kök");
    unmount();

    render(
      <WorkView
        transport={transport({
          getTask: vi.fn().mockResolvedValue({
            task: { ...taskA, project_id: "p-1", project_title: "Kök" },
          }),
        })}
        initial={{ kind: "task", id: taskA.id }}
        labels={workSv}
      />,
    );
    await screen.findByRole("button", { name: "Ändra plats: Kök" });
    expect(document.querySelector(".work-task-meta")).toBeNull();
    expect(document.querySelector(".work-task-late")).toBeNull();
  });

  it("does not call a done Task late and names only its date", async () => {
    const past = new Date(Date.now() - 5 * 86_400_000).toISOString();
    renderTask(
      transport({
        getTask: vi.fn().mockResolvedValue({
          task: { ...taskA, status: "completed", due_at: past },
        }),
      }),
    );
    const line = await dueLine();
    // Only the date: no "Was due" prefix, no distance and no overdue part.
    expect(line).not.toHaveTextContent(/Was due|overdue|days|·/);
    expect(line.textContent?.trim()).toMatch(/^\S+ \d{1,2} \S+$/);
  });

  it("offers Add date without a due date, and Tomorrow writes due_at 23:59 tomorrow through update_task", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(FROZEN_NOW);
    onTestFinished(() => {
      vi.useRealTimers();
    });
    const work = transport({
      updateTask: vi.fn().mockResolvedValue({
        task: { ...taskA, due_at: END_OF_TOMORROW, version: 2 },
      }),
    });
    renderTask(work);

    const user = userEvent.setup();
    const toggle = await screen.findByRole("button", { name: workEn.addDue });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    const choices = screen.getByRole("group", { name: workEn.addDue });
    expect(
      within(choices)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([
      workEn.dueToday,
      workEn.dueTomorrow,
      workEn.dueNextWeek,
      workEn.rescheduleDate,
    ]);
    await user.click(
      within(choices).getByRole("button", { name: workEn.dueTomorrow }),
    );

    await waitFor(() =>
      expect(work.updateTask).toHaveBeenCalledWith(
        taskA.id,
        1,
        { due_at: END_OF_TOMORROW },
        expect.any(String),
      ),
    );
    expect(
      screen.queryByRole("group", { name: workEn.addDue }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: new RegExp(`^${workEn.changeDue}: `),
      }),
    ).toBeVisible();
  });

  it("writes a chosen date from the date input, and Escape closes the choices", async () => {
    const work = transport({
      getTask: vi.fn().mockResolvedValue({
        task: {
          ...taskA,
          due_at: new Date(Date.now() + 3 * 86_400_000).toISOString(),
        },
      }),
    });
    renderTask(work);

    const user = userEvent.setup();
    const toggle = await screen.findByRole("button", {
      name: new RegExp(`^${workEn.changeDue}: `),
    });
    await user.click(toggle);
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("group", { name: workEn.changeDue }),
    ).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();

    await user.click(toggle);
    await user.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    const input = screen.getByLabelText(workEn.rescheduleDate, {
      selector: "input",
    });
    fireEvent.input(input, { target: { value: "2031-05-17" } });

    await waitFor(() =>
      expect(work.updateTask).toHaveBeenCalledWith(
        taskA.id,
        1,
        { due_at: "2031-05-17T21:59:00.000Z" },
        expect.any(String),
      ),
    );
  });
});
