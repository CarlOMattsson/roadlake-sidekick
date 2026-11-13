import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { manageLabelsSv } from "@/features/work-app/shared/manage-labels";
import { workSv } from "@/features/work-app/shared/labels";
import { TaskSteps } from "@/features/work-app/tasks/task-steps";
import type {
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// jsdom has no CSS global; the row controls use CSS.escape to find a control by its Step id.
if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";

function step(id: string, title: string, version: number): WorkStep {
  return { id, title, status: "todo", due_at: null, version, position: 0 };
}
const stepA = step("019f0000-0000-7000-8000-0000000000b1", "Ring Anna", 1);
const stepB = step("019f0000-0000-7000-8000-0000000000b2", "Skriv offert", 2);
const stepC = step("019f0000-0000-7000-8000-0000000000b3", "Skicka faktura", 3);

const page = (items: WorkStep[]) => ({ items, next_cursor: null });
const sv = manageLabelsSv;

/** The mocked transport; each test sets the writes it needs. */
function mockTransport(overrides: Record<string, unknown>) {
  const work = {
    listTaskSteps: vi.fn().mockResolvedValue(page([stepA, stepB, stepC])),
    reorderTaskSteps: vi.fn(),
    archiveTaskStep: vi.fn(),
    restoreTaskStep: vi.fn(),
    completeTaskStep: vi.fn(),
    updateTaskStep: vi.fn(),
    createTaskStep: vi.fn(),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    ...overrides,
  };
  return { work, transport: work as unknown as WorkTransport };
}

function renderSteps(transport: WorkTransport) {
  return render(
    <TaskSteps taskId={TASK_ID} transport={transport} labels={workSv} />,
  );
}

/** The Step's row (its `li`), found by its check. */
async function stepRow(title: string): Promise<HTMLElement> {
  const check = await screen.findByRole("checkbox", { name: title });
  return check.closest("li") as HTMLElement;
}

/**
 * Opens a Step row's menu, where its Up, Down and Archive buttons are drawn: a right click on the row, which a long
 * press on touch also gives.
 */
async function openMenu(title: string): Promise<void> {
  fireEvent.contextMenu(await stepRow(title));
}

/** Opens the "+ Lägg till steg" button, which shows the Step name field. */
async function openStepForm(user: UserEvent): Promise<void> {
  await user.click(await screen.findByRole("button", { name: workSv.addStep }));
}

/** The titles of the Step rows, in the order they are drawn. */
function rowTitles(): (string | null | undefined)[] {
  return screen
    .getAllByRole("listitem")
    .map((item) => item.querySelector("label > span")?.textContent);
}

describe("step archive and undo", () => {
  it("archives a step with its id, version and key, removes the row, and Ångra restores it with the archived version", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      listTaskSteps: vi
        .fn()
        .mockResolvedValueOnce(page([stepA, stepB, stepC]))
        .mockResolvedValue(page([stepA, { ...stepB, version: 4 }, stepC])),
      archiveTaskStep: vi.fn().mockResolvedValue({
        step: { ...stepB, version: 3, archived_at: "2026-11-02T10:00:00Z" },
      }),
      restoreTaskStep: vi.fn().mockResolvedValue({
        step: { ...stepB, version: 4 },
      }),
    });
    renderSteps(transport);

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );

    expect(work.archiveTaskStep).toHaveBeenCalledWith(
      stepB.id,
      2,
      expect.stringMatching(KEY),
    );
    expect(
      await screen.findByText(sv.archived(stepB.title)),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: stepB.title }),
    ).not.toBeInTheDocument();
    // The Undo line takes the focus after an archive.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: sv.undo })).toHaveFocus(),
    );

    await user.click(screen.getByRole("button", { name: sv.undo }));

    expect(work.restoreTaskStep).toHaveBeenCalledWith(
      stepB.id,
      3,
      expect.stringMatching(KEY),
    );
    await waitFor(() => expect(work.listTaskSteps).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("checkbox", { name: stepB.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(sv.restored(stepB.title))).toBeInTheDocument();
    // The restored row is drawn with its menu closed, so its check takes the focus.
    expect(screen.getByRole("checkbox", { name: stepB.title })).toHaveFocus();
  });

  it("restores a step archived earlier from the Archived list", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      archiveTaskStep: vi
        .fn()
        .mockResolvedValueOnce({ step: { ...stepB, version: 3 } })
        .mockResolvedValueOnce({ step: { ...stepC, version: 5 } }),
      restoreTaskStep: vi.fn().mockResolvedValue({
        step: { ...stepB, version: 4 },
      }),
      listTaskSteps: vi
        .fn()
        .mockResolvedValueOnce(page([stepA, stepB, stepC]))
        .mockResolvedValue(page([stepA, { ...stepB, version: 4 }])),
    });
    renderSteps(transport);

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    await openMenu(stepC.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepC.title) }),
    );
    const restore = await screen.findByRole("button", {
      name: sv.restoreFor(stepB.title),
    });
    await user.click(restore);

    expect(work.restoreTaskStep).toHaveBeenCalledWith(
      stepB.id,
      3,
      expect.stringMatching(KEY),
    );
    await waitFor(() => expect(work.listTaskSteps).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("checkbox", { name: stepB.title }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.restoreFor(stepB.title) }),
    ).not.toBeInTheDocument();
  });

  it("keeps a failed archive on its row and Försök igen sends the same key again", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      archiveTaskStep: vi
        .fn()
        .mockRejectedValueOnce(new Error("network"))
        .mockResolvedValue({ step: { ...stepB, version: 3 } }),
    });
    renderSteps(transport);

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(sv.failed);
    expect(
      screen.getByRole("checkbox", { name: stepB.title }),
    ).toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: sv.retry }));

    await waitFor(() => expect(work.archiveTaskStep).toHaveBeenCalledTimes(2));
    const calls = work.archiveTaskStep.mock.calls as unknown[][];
    const firstKey: unknown = calls[0]?.at(-1);
    expect(firstKey).toEqual(expect.stringMatching(KEY));
    expect(calls[1]?.at(-1)).toBe(firstKey);
    expect(
      await screen.findByText(sv.archived(stepB.title)),
    ).toBeInTheDocument();
  });
});

describe("step move", () => {
  it("sends the whole order with the versions held, shows Upp and Ned, and keeps focus on the moved row", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      reorderTaskSteps: vi.fn().mockResolvedValue(page([stepB, stepA, stepC])),
    });
    renderSteps(transport);

    await openMenu(stepA.title);
    await openMenu(stepB.title);
    await openMenu(stepC.title);
    const down = screen.getByRole("button", {
      name: sv.moveDownFor(stepA.title),
    });
    expect(down).toHaveTextContent(sv.down);
    expect(
      screen.getByRole("button", { name: sv.moveUpFor(stepA.title) }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: sv.moveDownFor(stepC.title) }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: sv.moveUpFor(stepB.title) }),
    ).toHaveTextContent(sv.up);
    expect(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    ).toHaveTextContent(sv.archive);

    await user.click(down);

    expect(work.reorderTaskSteps).toHaveBeenCalledWith(
      TASK_ID,
      [
        { id: stepB.id, version: 2 },
        { id: stepA.id, version: 1 },
        { id: stepC.id, version: 3 },
      ],
      expect.stringMatching(KEY),
    );
    expect(
      await screen.findByText(sv.moved(stepA.title, 2, 3)),
    ).toBeInTheDocument();
    expect(rowTitles()).toEqual([stepB.title, stepA.title, stepC.title]);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: sv.moveDownFor(stepA.title) }),
      ).toHaveFocus(),
    );
  });

  it("moves a row up and keeps focus on its Upp button", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      reorderTaskSteps: vi.fn().mockResolvedValue(page([stepA, stepC, stepB])),
    });
    renderSteps(transport);

    await openMenu(stepC.title);
    await user.click(
      screen.getByRole("button", { name: sv.moveUpFor(stepC.title) }),
    );

    expect(work.reorderTaskSteps).toHaveBeenCalledWith(
      TASK_ID,
      [
        { id: stepA.id, version: 1 },
        { id: stepC.id, version: 3 },
        { id: stepB.id, version: 2 },
      ],
      expect.stringMatching(KEY),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: sv.moveUpFor(stepC.title) }),
      ).toHaveFocus(),
    );
  });
});

describe("step list refusals", () => {
  it("shows the conflict warning and Ladda om reads the list again", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      archiveTaskStep: vi.fn().mockRejectedValue({ code: "conflict" }),
    });
    renderSteps(transport);

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(sv.conflict);
    await waitFor(() => expect(alert).toHaveFocus());

    await user.click(within(alert).getByRole("button", { name: sv.reload }));

    await waitFor(() => expect(work.listTaskSteps).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("checkbox", { name: stepB.title }),
    ).toBeInTheDocument();
  });
});

describe("step notices and the Archived list", () => {
  it("replaces the Steget lades till line with the next action's status, so one status line shows", async () => {
    const user = userEvent.setup();
    const created: WorkStep = {
      id: "019f0000-0000-7000-8000-0000000000b4",
      title: "Ny kontroll",
      status: "todo",
      due_at: null,
      version: 1,
      position: 3,
    };
    const { work, transport } = mockTransport({
      createTaskStep: vi.fn().mockResolvedValue({ step: created }),
      archiveTaskStep: vi.fn().mockResolvedValue({
        step: { ...stepB, version: 3, archived_at: "2026-11-02T10:00:00Z" },
      }),
    });
    renderSteps(transport);
    await screen.findByRole("checkbox", { name: stepA.title });

    await openStepForm(user);
    await user.type(screen.getByLabelText(workSv.stepTitle), created.title);
    await user.click(screen.getByRole("button", { name: workSv.addStep }));
    expect(await screen.findByText(workSv.stepAdded)).toBeInTheDocument();

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    expect(
      await screen.findByText(sv.archived(stepB.title)),
    ).toBeInTheDocument();
    // The archive's Undo line is the only status now: the add notice is gone.
    expect(screen.queryByText(workSv.stepAdded)).not.toBeInTheDocument();
    expect(work.createTaskStep).toHaveBeenCalledTimes(1);
  });

  it("keeps an archived Step out of the Archived list while its Ångra line shows", async () => {
    const user = userEvent.setup();
    const { transport } = mockTransport({
      archiveTaskStep: vi
        .fn()
        .mockResolvedValueOnce({ step: { ...stepB, version: 3 } })
        .mockResolvedValueOnce({ step: { ...stepC, version: 5 } }),
    });
    renderSteps(transport);

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    expect(
      await screen.findByText(sv.archived(stepB.title)),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.restoreFor(stepB.title) }),
    ).not.toBeInTheDocument();

    await openMenu(stepC.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepC.title) }),
    );
    // Archiving C moves the Undo line to it; B has no Undo line any more and joins the list.
    expect(
      await screen.findByRole("button", { name: sv.restoreFor(stepB.title) }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.restoreFor(stepC.title) }),
    ).not.toBeInTheDocument();
  });

  it("clears the restored notice when a checkbox write starts, so a conflict shows alone", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      archiveTaskStep: vi
        .fn()
        .mockResolvedValue({ step: { ...stepB, version: 3 } }),
      restoreTaskStep: vi
        .fn()
        .mockResolvedValue({ step: { ...stepB, version: 4 } }),
      completeTaskStep: vi.fn().mockRejectedValue({ code: "conflict" }),
    });
    renderSteps(transport);

    await openMenu(stepB.title);
    await user.click(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    );
    await user.click(await screen.findByRole("button", { name: sv.undo }));
    expect(
      await screen.findByText(sv.restored(stepB.title)),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: stepA.title })).toBeEnabled(),
    );
    await user.click(screen.getByRole("checkbox", { name: stepA.title }));
    expect(await screen.findByText(workSv.stepConflict)).toBeInTheDocument();
    expect(
      screen.queryByText(sv.restored(stepB.title)),
    ).not.toBeInTheDocument();
    expect(work.completeTaskStep).toHaveBeenCalledTimes(1);
  });
});

describe("step row menu and name field", () => {
  it("draws Up, Down and Archive only inside the Step's menu, which a right click or Shift+F10 opens and Escape closes", async () => {
    const user = userEvent.setup();
    const { transport } = mockTransport({});
    renderSteps(transport);

    const check = await screen.findByRole("checkbox", { name: stepA.title });
    const row = check.closest("li") as HTMLElement;
    // The only "Fler val" button on a Step is the one drawn nowhere, for a screen reader; no ⋯ is drawn.
    for (const more of screen.getAllByRole("button", { name: /Fler val/ }))
      expect(more).toHaveClass("work-visually-hidden");
    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.moveUpFor(stepA.title) }),
    ).not.toBeInTheDocument();

    fireEvent.contextMenu(row);

    expect(
      screen.getByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: sv.moveUpFor(stepA.title) }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: sv.moveDownFor(stepA.title) }),
    ).toBeEnabled();

    check.focus();
    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.moveUpFor(stepA.title) }),
    ).not.toBeInTheDocument();
  });

  it("creates on Enter, empties the field and keeps the focus there so several Steps can be typed in a row", async () => {
    const user = userEvent.setup();
    const first = {
      ...step("019f0000-0000-7000-8000-0000000000b4", "Boka tid", 4),
    };
    const second = {
      ...step("019f0000-0000-7000-8000-0000000000b5", "Skicka kallelse", 5),
    };
    const { work, transport } = mockTransport({
      createTaskStep: vi
        .fn()
        .mockResolvedValueOnce({ step: first })
        .mockResolvedValueOnce({ step: second }),
    });
    renderSteps(transport);
    await openStepForm(user);

    const name = screen.getByRole("textbox", { name: workSv.stepTitle });
    expect(name).toHaveAttribute("placeholder", workSv.stepPlaceholder);
    // Empty, the square is × and closes; with text it is the primary +.
    expect(
      screen.getByRole("button", { name: workSv.closeStepField }),
    ).toBeInTheDocument();
    await user.type(name, "Boka tid{Enter}");
    await waitFor(() => expect(name).toHaveValue(""));
    expect(name).toHaveFocus();
    await user.type(name, "Skicka kallelse{Enter}");
    await waitFor(() => expect(work.createTaskStep).toHaveBeenCalledTimes(2));
    expect(work.createTaskStep).toHaveBeenNthCalledWith(
      1,
      TASK_ID,
      "Boka tid",
      expect.stringMatching(KEY),
    );
    expect(
      await screen.findByRole("checkbox", { name: "Skicka kallelse" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(name).toHaveValue(""));
    expect(name).toHaveFocus();
  });

  it("closes on Esc and on the empty field's x, and gives the focus back to the quiet + Lägg till steg line", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({});
    renderSteps(transport);
    await openStepForm(user);
    await user.type(
      screen.getByRole("textbox", { name: workSv.stepTitle }),
      "{Escape}",
    );
    expect(
      screen.queryByRole("textbox", { name: workSv.stepTitle }),
    ).not.toBeInTheDocument();
    const opener = screen.getByRole("button", { name: workSv.addStep });
    expect(opener).toHaveFocus();

    await user.click(opener);
    await user.click(
      screen.getByRole("button", { name: workSv.closeStepField }),
    );
    expect(
      screen.queryByRole("textbox", { name: workSv.stepTitle }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: workSv.addStep })).toHaveFocus();
    expect(work.createTaskStep).not.toHaveBeenCalled();
  });

  it("does not send a blank title and names a title over the limit under the field without sending it", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({});
    renderSteps(transport);
    await openStepForm(user);
    const name = screen.getByRole("textbox", { name: workSv.stepTitle });

    await user.type(name, "   {Enter}");
    expect(work.createTaskStep).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.clear(name);
    await user.click(name);
    await user.paste("x".repeat(201));
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      workSv.titleTooLong,
    );
    expect(work.createTaskStep).not.toHaveBeenCalled();
    expect(name).toHaveValue("x".repeat(201));

    // The line goes away when the title is edited.
    await user.type(name, "y");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the text of a failed write, and Försök igen sends the same title with the same idempotency key", async () => {
    const user = userEvent.setup();
    const created = step("019f0000-0000-7000-8000-0000000000b4", "Boka tid", 4);
    const { work, transport } = mockTransport({
      createTaskStep: vi
        .fn()
        .mockRejectedValueOnce(new Error("network"))
        .mockResolvedValueOnce({ step: created }),
    });
    renderSteps(transport);
    await openStepForm(user);
    const name = screen.getByRole("textbox", { name: workSv.stepTitle });
    await user.type(name, "Boka tid{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      workSv.stepCreateFailed,
    );
    expect(name).toHaveValue("Boka tid");
    await user.click(screen.getByRole("button", { name: workSv.retry }));

    expect(
      await screen.findByRole("checkbox", { name: "Boka tid" }),
    ).toBeInTheDocument();
    expect(work.createTaskStep).toHaveBeenCalledTimes(2);
    const firstKey = (work.createTaskStep.mock.calls[0] as unknown[])[2];
    expect(work.createTaskStep.mock.calls[1]).toEqual([
      TASK_ID,
      "Boka tid",
      firstKey,
    ]);
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: workSv.stepTitle }),
      ).toHaveValue(""),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sends nothing more while a write is in the air", async () => {
    const user = userEvent.setup();
    let resolve: (value: unknown) => void = () => {};
    const { work, transport } = mockTransport({
      createTaskStep: vi.fn().mockReturnValue(
        new Promise((done) => {
          resolve = done;
        }),
      ),
    });
    renderSteps(transport);
    await openStepForm(user);
    await user.type(
      screen.getByRole("textbox", { name: workSv.stepTitle }),
      "Boka tid{Enter}{Enter}{Enter}",
    );
    expect(work.createTaskStep).toHaveBeenCalledTimes(1);
    resolve({
      step: step("019f0000-0000-7000-8000-0000000000b4", "Boka tid", 4),
    });
    expect(
      await screen.findByRole("checkbox", { name: "Boka tid" }),
    ).toBeInTheDocument();
  });
});

describe("step progress, undo of a check and the quiet forms", () => {
  it("counts the done Steps in the heading, dims them, and leaves the count out while more Steps exist", async () => {
    const { transport } = mockTransport({
      listTaskSteps: vi
        .fn()
        .mockResolvedValue(page([{ ...stepA, status: "completed" }, stepB])),
    });
    renderSteps(transport);

    expect(
      await screen.findByRole("heading", { name: "Steg · 1 av 2 klara" }),
    ).toBeInTheDocument();
    const checked = screen.getByRole("checkbox", { name: stepA.title });
    expect(checked).toBeChecked();
    expect(checked.closest("li")).toHaveClass("work-step-done");
    expect(
      screen.getByRole("checkbox", { name: stepB.title }).closest("li"),
    ).not.toHaveClass("work-step-done");
  });

  it("shows Klar with Ångra after a check, and Ångra writes the other state against the version the check left", async () => {
    const user = userEvent.setup();
    const { work, transport } = mockTransport({
      completeTaskStep: vi.fn().mockResolvedValue({
        step: { ...stepA, status: "completed", version: 2 },
      }),
      updateTaskStep: vi.fn().mockResolvedValue({
        step: { ...stepA, status: "todo", version: 3 },
      }),
    });
    renderSteps(transport);
    await user.click(
      await screen.findByRole("checkbox", { name: stepA.title }),
    );

    expect(work.completeTaskStep).toHaveBeenCalledWith(
      stepA.id,
      1,
      expect.stringMatching(KEY),
    );
    // Ångra stands in the Step's own row, and the row's meta line says "Klar".
    const undo = await screen.findByRole("button", { name: sv.undo });
    expect(undo.closest("li")).toBe(await stepRow(stepA.title));
    expect(screen.getByRole("status")).toHaveTextContent("Klar");
    await user.click(undo);

    await waitFor(() =>
      expect(work.updateTaskStep).toHaveBeenCalledWith(
        stepA.id,
        2,
        { status: "todo" },
        expect.stringMatching(KEY),
      ),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: sv.undo }),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps the Step name field closed until the quiet line is pressed, then puts the focus in it", async () => {
    const user = userEvent.setup();
    const { transport } = mockTransport({});
    renderSteps(transport);
    await screen.findByRole("checkbox", { name: stepA.title });

    expect(
      screen.queryByRole("textbox", { name: workSv.stepTitle }),
    ).not.toBeInTheDocument();
    await openStepForm(user);
    expect(
      screen.getByRole("textbox", { name: workSv.stepTitle }),
    ).toHaveFocus();
  });

  it("closes the menu with its Stäng button, and the focus goes to the Step's checkbox", async () => {
    const user = userEvent.setup();
    const { transport } = mockTransport({});
    renderSteps(transport);
    const check = await screen.findByRole("checkbox", { name: stepB.title });

    await openMenu(stepB.title);
    expect(
      screen.getByRole("button", { name: sv.moveUpFor(stepB.title) }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: workSv.closeMenu }));

    expect(
      screen.queryByRole("button", { name: sv.moveUpFor(stepB.title) }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.moveDownFor(stepB.title) }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepB.title) }),
    ).not.toBeInTheDocument();
    expect(check).toHaveFocus();
  });

  it("draws no Actions entry in the Step's menu: the count under the title opens them", async () => {
    const { transport } = mockTransport({});
    renderSteps(transport);
    await screen.findByRole("checkbox", { name: stepA.title });

    await openMenu(stepA.title);
    expect(
      screen.queryByRole("button", { name: /åtgärd/ }),
    ).not.toBeInTheDocument();
    // The menu has its own close button, labelled as the menu's close.
    expect(
      screen.getByRole("button", { name: workSv.closeMenu }),
    ).toBeInTheDocument();
    expect(transport.listStepActions).not.toHaveBeenCalled();
  });
});

// A Task with no Steps shows only "+ Lägg till steg"; the "Steg" heading is read by assistive
// technology but not drawn, and it is drawn again with the first Step.
describe("the Steps heading of a Task with no Steps", () => {
  it("is visually hidden while the list is empty and drawn when a Step exists", async () => {
    const empty = mockTransport({
      listTaskSteps: vi.fn().mockResolvedValue(page([])),
    });
    const { unmount } = renderSteps(empty.transport);
    await screen.findByRole("button", { name: workSv.addStep });
    const hidden = screen.getByRole("heading", { name: workSv.steps });
    expect(hidden).toHaveClass("work-visually-hidden");
    unmount();
    renderSteps(mockTransport({}).transport);
    const shown = await screen.findByRole("heading", {
      name: "Steg · 0 av 3 klara",
    });
    expect(shown).not.toHaveClass("work-visually-hidden");
  });
});
