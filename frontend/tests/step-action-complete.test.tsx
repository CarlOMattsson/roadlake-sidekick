import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { manageLabelsSv } from "@/features/work-app/shared/manage-labels";
import { StepActions } from "@/features/work-app/steps/step-actions";
import type {
  WorkAction,
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// jsdom has no CSS global; the row controls use CSS.escape to find a control by its id.
if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const step: WorkStep = {
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Ring Anna",
  status: "todo",
  due_at: null,
  version: 1,
};
const open: WorkAction = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  step_id: step.id,
  title: "Ring receptionen",
  status: "todo",
  due_at: null,
  version: 4,
  position: 0,
};
const done: WorkAction = {
  ...open,
  id: "019f0000-0000-7000-8000-0000000000e2",
  title: "Skicka mejlet",
  status: "completed",
  version: 7,
  position: 1,
};
const blocked: WorkAction = {
  ...open,
  id: "019f0000-0000-7000-8000-0000000000e3",
  title: "Vänta på svar",
  status: "blocked",
  position: 2,
};

function setup(overrides: Record<string, unknown> = {}) {
  return {
    listStepActions: vi.fn(() =>
      Promise.resolve({ items: [open, done, blocked], next_cursor: null }),
    ),
    completeStepAction: vi.fn(() =>
      Promise.resolve({
        action: { ...open, status: "completed", version: 5 },
      }),
    ),
    reopenStepAction: vi.fn(() =>
      Promise.resolve({
        action: { ...done, status: "open", version: 8 },
      }),
    ),
    reorderStepActions: vi.fn(),
    archiveStepAction: vi.fn(),
    restoreStepAction: vi.fn(),
    ...overrides,
  } as unknown as WorkTransport;
}

async function show(transport: WorkTransport, labels = workSv) {
  render(
    <StepActions
      step={step}
      transport={transport}
      labels={labels}
      open
      onCount={vi.fn()}
    />,
  );
  await screen.findByText("Ring receptionen");
}

it("ticks an open Action with its version and an idempotency key", async () => {
  const user = userEvent.setup();
  const transport = setup();
  await show(transport);

  const box = screen.getByRole("checkbox", { name: "Ring receptionen" });
  expect(box).not.toBeChecked();
  await user.click(box);

  expect(transport.completeStepAction).toHaveBeenCalledWith(
    open.id,
    4,
    expect.stringMatching(KEY),
  );
  await waitFor(() => expect(box).toBeChecked());
});

it("draws a done Action ticked and dimmed, and says only a state the box cannot say", async () => {
  await show(setup());

  const box = screen.getByRole("checkbox", { name: "Skicka mejlet" });
  expect(box).toBeChecked();
  expect(box).toBeEnabled();
  expect(box).not.toHaveAttribute("aria-readonly");
  expect(box.closest("li")).toHaveClass("work-step-action-done");
  // The box says it: no "Klar" or "Att göra" is written out, only a state the box cannot say.
  expect(screen.queryByText("Klar")).not.toBeInTheDocument();
  expect(screen.queryByText("Att göra")).not.toBeInTheDocument();
  expect(screen.getByText("Blockerad")).toBeInTheDocument();
});

it("unticks a done Action with its version and an idempotency key, and draws it open", async () => {
  const user = userEvent.setup();
  const transport = setup();
  await show(transport);

  const box = screen.getByRole("checkbox", { name: "Skicka mejlet" });
  await user.click(box);

  expect(transport.reopenStepAction).toHaveBeenCalledWith(
    done.id,
    7,
    expect.stringMatching(KEY),
  );
  expect(transport.completeStepAction).not.toHaveBeenCalled();
  await waitFor(() => expect(box).not.toBeChecked());
  expect(box.closest("li")).not.toHaveClass("work-step-action-done");
  // The server's word for an open Action is "open"; the row shows no state for it.
  expect(screen.queryByText("open")).not.toBeInTheDocument();
  // Ticking it again uses the version the reopen answered.
  await user.click(box);
  expect(transport.completeStepAction).toHaveBeenCalledWith(
    done.id,
    8,
    expect.stringMatching(KEY),
  );
});

it("sets an unticked Action back to done when the write fails, and Try again reuses the key", async () => {
  const user = userEvent.setup();
  const reopen = vi
    .fn()
    .mockRejectedValueOnce(Object.assign(new Error("x"), { code: "internal" }))
    .mockResolvedValue({ action: { ...done, status: "open", version: 8 } });
  await show(setup({ reopenStepAction: reopen }));

  const box = screen.getByRole("checkbox", { name: "Skicka mejlet" });
  await user.click(box);
  expect(await screen.findByText(manageLabelsSv.failed)).toBeInTheDocument();
  expect(box).toBeChecked();

  await user.click(screen.getByRole("button", { name: "Försök igen" }));
  await waitFor(() => expect(box).not.toBeChecked());
  expect(reopen).toHaveBeenCalledTimes(2);
  expect(reopen.mock.calls[1]?.[2]).toBe(reopen.mock.calls[0]?.[2]);
});

it("keeps a done Action ticked and read-only when the host cannot update Actions", async () => {
  const user = userEvent.setup();
  const transport = {
    ...setup(),
    supportsTool: (name: string) => name !== "update_step_action",
  } as unknown as WorkTransport;
  await show(transport);

  const box = screen.getByRole("checkbox", { name: "Skicka mejlet" });
  expect(box).toHaveAttribute("aria-readonly", "true");
  // Not disabled, so it does not look broken; it just does not change.
  expect(box).toBeEnabled();
  await user.click(box);
  expect(box).toBeChecked();
  expect(transport.reopenStepAction).not.toHaveBeenCalled();
  expect(transport.completeStepAction).not.toHaveBeenCalled();
});

it("shows the tick at once, sets it back when the write fails, and Try again reuses the key", async () => {
  const user = userEvent.setup();
  let answer: (value: unknown) => void = () => undefined;
  const complete = vi
    .fn()
    .mockRejectedValueOnce(Object.assign(new Error("x"), { code: "internal" }))
    .mockImplementation(() => new Promise((resolve) => (answer = resolve)));
  await show(setup({ completeStepAction: complete }));

  const box = screen.getByRole("checkbox", { name: "Ring receptionen" });
  await user.click(box);
  const failed = await screen.findByText(manageLabelsSv.failed);
  expect(failed).toBeInTheDocument();
  expect(box).not.toBeChecked();

  await user.click(screen.getByRole("button", { name: "Försök igen" }));
  // The retry is drawn before the server has answered.
  expect(box).toBeChecked();
  expect(complete).toHaveBeenCalledTimes(2);
  expect(complete.mock.calls[1]?.[2]).toBe(complete.mock.calls[0]?.[2]);
  act(() => {
    answer({ action: { ...open, status: "completed", version: 5 } });
  });
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(2));
  expect(box).toBeChecked();
});

it("offers no box when the host can neither complete nor update Actions, and shows the state as a mark", async () => {
  const transport = {
    ...setup(),
    supportsTool: (name: string) =>
      name !== "complete_step_action" && name !== "update_step_action",
  } as unknown as WorkTransport;
  await show(transport);

  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Klar" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Att göra" })).toBeInTheDocument();
});

it("keeps Up, Down and Archive out of sight until the row's menu is opened", async () => {
  const user = userEvent.setup();
  await show(setup());

  expect(
    screen.queryByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Flytta ned: Ring receptionen" }),
  ).not.toBeInTheDocument();

  // A long press or a right click opens it for that row only.
  fireEvent.contextMenu(
    screen.getByRole("checkbox", { name: "Ring receptionen" }).closest("li")!,
  );
  expect(
    screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Arkivera: Skicka mejlet" }),
  ).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: workSv.closeMenu }));
  expect(
    screen.queryByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).not.toBeInTheDocument();
});

it("opens the menu with the hidden button, which puts the focus on its first choice", async () => {
  const user = userEvent.setup();
  await show(setup());

  await user.click(
    screen.getByRole("button", { name: "Fler val för Ring receptionen" }),
  );
  expect(
    screen.getByRole("button", { name: "Flytta ned: Ring receptionen" }),
  ).toHaveFocus();
});

it("opens the menu with Shift+F10 on the Action only, and Escape closes it back to the box", async () => {
  const user = userEvent.setup();
  await show(setup());

  const box = screen.getByRole("checkbox", { name: "Ring receptionen" });
  box.focus();
  await user.keyboard("{Shift>}{F10}{/Shift}");
  expect(
    screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).toBeInTheDocument();

  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).not.toBeInTheDocument();
  expect(box).toHaveFocus();
});

it("archives from the menu with the keyboard", async () => {
  const user = userEvent.setup();
  const transport = setup({
    archiveStepAction: vi.fn(() =>
      Promise.resolve({ action: { ...open, version: 5 } }),
    ),
  });
  await show(transport);

  screen.getByRole("checkbox", { name: "Ring receptionen" }).focus();
  await user.keyboard("{Shift>}{F10}{/Shift}");
  await user.click(
    screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
  );
  expect(transport.archiveStepAction).toHaveBeenCalledWith(
    open.id,
    4,
    expect.stringMatching(KEY),
  );
});

it("words the menu hint and the hidden button in English", async () => {
  await show(setup(), workEn);

  const box = screen.getByRole("checkbox", { name: "Ring receptionen" });
  expect(box).toHaveAttribute("aria-keyshortcuts", "Shift+F10");
  expect(
    screen.getByRole("button", { name: "More options for Ring receptionen" }),
  ).toBeInTheDocument();
});

it("keeps a ticked Action in its place with Klar and Ångra, and Ångra writes the other state against the new version", async () => {
  const user = userEvent.setup();
  const transport = setup();
  await show(transport);

  await user.click(screen.getByRole("checkbox", { name: "Ring receptionen" }));
  const row = screen
    .getByRole("checkbox", { name: "Ring receptionen" })
    .closest("li");
  expect(await screen.findByText("Klar")).toBeInTheDocument();
  expect(row).toHaveClass("work-step-undoing");

  await user.click(screen.getByRole("button", { name: workSv.agendaUndo }));
  expect(transport.reopenStepAction).toHaveBeenCalledWith(
    open.id,
    5,
    expect.stringMatching(KEY),
  );
  await waitFor(() =>
    expect(screen.queryByText("Klar")).not.toBeInTheDocument(),
  );
  // Undoing offers no second Ångra.
  expect(
    screen.queryByRole("button", { name: workSv.agendaUndo }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", { name: "Ring receptionen" }),
  ).not.toBeChecked();
});

it("says Öppen igen after an untick, and another write takes the Ångra away", async () => {
  const user = userEvent.setup();
  const transport = setup({
    archiveStepAction: vi.fn(() =>
      Promise.resolve({
        action: { ...open, version: 5, archived_at: "2026-11-02T08:00:00Z" },
      }),
    ),
  });
  await show(transport);

  await user.click(screen.getByRole("checkbox", { name: "Skicka mejlet" }));
  expect(await screen.findByText("Öppen igen")).toBeInTheDocument();

  fireEvent.contextMenu(
    screen
      .getByRole("checkbox", { name: "Ring receptionen" })
      .closest("li") as HTMLElement,
  );
  await user.click(
    screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
  );
  await waitFor(() =>
    expect(screen.queryByText("Öppen igen")).not.toBeInTheDocument(),
  );
});

it("shows the due day under the title, red when it has passed, and the note on the same line; a done Action names no day", async () => {
  const soon = new Date(Date.now() + 36 * 3600 * 1000).toISOString();
  const late = new Date(Date.now() - 4 * 24 * 3600 * 1000).toISOString();
  const withMeta: WorkAction = {
    ...open,
    due_at: soon,
    note: "Bifoga kvitton",
  };
  const overdue: WorkAction = { ...blocked, due_at: late };
  const doneLate: WorkAction = { ...done, due_at: late, note: "Skickat" };
  await show(
    setup({
      listStepActions: vi.fn(() =>
        Promise.resolve({
          items: [withMeta, overdue, doneLate],
          next_cursor: null,
        }),
      ),
    }),
    workEn,
  );

  const meta = screen.getByText(/Bifoga kvitton/);
  expect(meta).toHaveClass("work-step-action-meta");
  expect(meta.textContent).toMatch(/ · Bifoga kvitton$/);
  const passed = screen.getByText(/overdue/);
  expect(passed).toHaveAttribute("data-tone", "overdue");
  // A done Action is not overdue: its day is left out and only the note stays.
  expect(screen.getByText("Skickat")).toHaveClass("work-step-action-meta");
  expect(screen.getAllByText(/overdue/)).toHaveLength(1);
  // The box is named by the title alone; the day and the note are its description.
  const box = screen.getByRole("checkbox", { name: withMeta.title });
  expect(box).toHaveAccessibleDescription(
    new RegExp(`^${meta.textContent ?? ""}`),
  );
});
