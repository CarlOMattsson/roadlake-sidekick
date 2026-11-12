import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { StepActions } from "@/features/work-app/step-actions";
import {
  stepActionsLabelsEn,
  stepActionsLabelsSv,
} from "@/features/work-app/step-actions-labels";
import { manageLabelsSv } from "@/features/work-app/manage-labels";
import { workSv } from "@/features/work-app/labels";
import type {
  WorkAction,
  WorkActionPage,
  WorkOrderItem,
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport";

// jsdom has no CSS global; focusControl selects its control with CSS.escape, as the browser does.
const cssGlobal = globalThis as unknown as {
  CSS?: { escape: (value: string) => string };
};
cssGlobal.CSS ??= {
  escape: (value: string) => value.replace(/[^\w-]/g, (ch) => `\\${ch}`),
};

const STEP_ID = "019f0000-0000-7000-8000-0000000000f1";
const FIRST_ID = "019f0000-0000-7000-8000-0000000000e1";
const SECOND_ID = "019f0000-0000-7000-8000-0000000000e2";
const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const step: WorkStep = {
  id: STEP_ID,
  title: "Ring Anna",
  status: "todo",
  due_at: null,
  version: 1,
};
const first: WorkAction = {
  id: FIRST_ID,
  step_id: STEP_ID,
  title: "Ring receptionen",
  status: "todo",
  due_at: null,
  version: 1,
  position: 0,
};
const second: WorkAction = {
  id: SECOND_ID,
  step_id: STEP_ID,
  title: "Skicka mejlet",
  status: "completed",
  due_at: null,
  version: 3,
  position: 1,
};

const ORIGINAL: WorkActionPage = {
  items: [first, second],
  next_cursor: null,
};

/** A refusal as the transport throws it: an Error that carries the server's code. */
function refusal(code: string) {
  return Object.assign(new Error(code), { code });
}

/** A reorder answer: the items in the sent order, each with the version bumped by one. */
function reordered(items: WorkOrderItem[]): WorkActionPage {
  return {
    items: items.map((item, index) => {
      const found = [first, second].find((action) => action.id === item.id);
      return { ...found!, position: index, version: item.version + 1 };
    }),
    next_cursor: null,
  };
}

function setup(overrides: Partial<WorkTransport> = {}) {
  return {
    listStepActions: vi.fn(() => Promise.resolve(ORIGINAL)),
    reorderStepActions: vi.fn((_stepId: string, items: WorkOrderItem[]) =>
      Promise.resolve(reordered(items)),
    ),
    archiveStepAction: vi.fn(() =>
      Promise.resolve({
        action: { ...first, version: 2, archived_at: "2026-11-02T08:00:00Z" },
      }),
    ),
    restoreStepAction: vi.fn(() =>
      Promise.resolve({ action: { ...first, version: 3 } }),
    ),
    ...overrides,
  } as unknown as WorkTransport;
}

/**
 * The Step row's side of the Actions: its ⋯ menu's "Visa åtgärder" button opens and closes them, and
 * StepActions draws nothing while they are closed.
 */
function ActionsHarness({ transport }: { transport: WorkTransport }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? stepActionsLabelsSv.hide : stepActionsLabelsSv.show}
      </button>
      <StepActions
        step={step}
        transport={transport}
        labels={workSv}
        open={open}
      />
    </>
  );
}

async function openActions(
  user: ReturnType<typeof userEvent.setup>,
  transport: WorkTransport,
) {
  render(<ActionsHarness transport={transport} />);
  await user.click(screen.getByRole("button", { name: "Visa åtgärder" }));
  await screen.findByText("Ring receptionen");
}

it("reads the actions only when the button is opened, then lists them with their status", async () => {
  const user = userEvent.setup();
  const transport = setup();
  render(<ActionsHarness transport={transport} />);

  expect(transport.listStepActions).not.toHaveBeenCalled();
  const regionName = "Åtgärder för steget Ring Anna";
  expect(
    screen.queryByRole("region", { name: regionName }),
  ).not.toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "Visa åtgärder" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");

  await user.click(toggle);
  expect(transport.listStepActions).toHaveBeenCalledWith(STEP_ID);
  const region = screen.getByRole("region", { name: regionName });
  expect(await screen.findByText("Ring receptionen")).toBeInTheDocument();
  expect(screen.getByText("Skicka mejlet")).toBeInTheDocument();
  expect(screen.getByText("Att göra")).toBeInTheDocument();
  expect(screen.getByText("Klar")).toBeInTheDocument();
  expect(screen.getByText("Åtgärder (2)")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Dölj åtgärder" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );

  await user.click(screen.getByRole("button", { name: "Dölj åtgärder" }));
  expect(region).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Visa åtgärder" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

it("shows Laddar while the list is read", async () => {
  const user = userEvent.setup();
  let answer: (page: WorkActionPage) => void = () => undefined;
  const transport = setup({
    listStepActions: vi.fn(
      () => new Promise<WorkActionPage>((resolve) => (answer = resolve)),
    ),
  });
  render(<ActionsHarness transport={transport} />);
  await user.click(screen.getByRole("button", { name: "Visa åtgärder" }));

  expect(screen.getByText("Laddar…")).toHaveAttribute("role", "status");
  act(() => {
    answer(ORIGINAL);
  });
  expect(await screen.findByText("Ring receptionen")).toBeInTheDocument();
  expect(screen.queryByText("Laddar…")).not.toBeInTheDocument();
});

it("says there are no actions when the Step has none", async () => {
  const user = userEvent.setup();
  const transport = setup({
    listStepActions: vi.fn(() =>
      Promise.resolve({ items: [], next_cursor: null }),
    ),
  });
  render(<ActionsHarness transport={transport} />);
  await user.click(screen.getByRole("button", { name: "Visa åtgärder" }));

  expect(await screen.findByText("Inga åtgärder.")).toBeInTheDocument();
});

it("disables Up on the first row and Down on the last", async () => {
  const user = userEvent.setup();
  await openActions(user, setup());

  expect(
    screen.getByRole("button", { name: "Flytta upp: Ring receptionen" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Flytta ned: Skicka mejlet" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Flytta ned: Ring receptionen" }),
  ).toBeEnabled();
});

it("moves an Action with the whole list and the versions the view holds, then keeps focus on it", async () => {
  const user = userEvent.setup();
  const transport = setup();
  await openActions(user, transport);

  await user.click(
    screen.getByRole("button", { name: "Flytta ned: Ring receptionen" }),
  );
  expect(transport.reorderStepActions).toHaveBeenCalledWith(
    STEP_ID,
    [
      { id: SECOND_ID, version: 3 },
      { id: FIRST_ID, version: 1 },
    ],
    expect.stringMatching(KEY),
  );
  expect(
    await screen.findByText("Flyttade ”Ring receptionen” till plats 2 av 2."),
  ).toBeInTheDocument();
  const rows = screen.getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("Skicka mejlet");
  expect(rows[1]).toHaveTextContent("Ring receptionen");
  // The moved row is last now, so its Down is disabled and focus goes to its Up.
  expect(
    screen.getByRole("button", { name: "Flytta upp: Ring receptionen" }),
  ).toHaveFocus();

  // The next move uses the versions of the answer, not the ones from the first read.
  await user.click(
    screen.getByRole("button", { name: "Flytta ned: Skicka mejlet" }),
  );
  expect(transport.reorderStepActions).toHaveBeenLastCalledWith(
    STEP_ID,
    [
      { id: FIRST_ID, version: 2 },
      { id: SECOND_ID, version: 4 },
    ],
    expect.stringMatching(KEY),
  );
});

it("archives an Action, offers Undo, and Undo restores it and reads the list again", async () => {
  const user = userEvent.setup();
  const transport = setup();
  await openActions(user, transport);

  await user.click(
    screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
  );
  expect(transport.archiveStepAction).toHaveBeenCalledWith(
    FIRST_ID,
    1,
    expect.stringMatching(KEY),
  );
  expect(
    screen.queryByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("Arkiverade ”Ring receptionen”."),
  ).toBeInTheDocument();
  // The Undo line takes the focus; the archived Action joins the Archived list only once it has gone.
  expect(screen.getByRole("button", { name: "Ångra" })).toHaveFocus();
  expect(
    screen.queryByRole("region", { name: "Arkiverade (1)" }),
  ).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Ångra" }));
  expect(transport.restoreStepAction).toHaveBeenCalledWith(
    FIRST_ID,
    2,
    expect.stringMatching(KEY),
  );
  expect(transport.listStepActions).toHaveBeenCalledTimes(2);
  expect(
    await screen.findByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).toHaveFocus();
  expect(
    screen.getByText("Återställde ”Ring receptionen”."),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Ångra" }),
  ).not.toBeInTheDocument();
});

it("restores an archived Action from the archived list and puts focus on its row", async () => {
  const user = userEvent.setup();
  const transport = setup();
  await openActions(user, transport);

  await user.click(
    screen.getByRole("button", { name: "Arkivera: Ring receptionen" }),
  );
  // Archiving the next Action moves the Undo line to it; the first Action then joins the Archived list.
  await user.click(
    screen.getByRole("button", { name: "Arkivera: Skicka mejlet" }),
  );
  const archivedSection = screen.getByRole("region", {
    name: "Arkiverade (1)",
  });
  await user.click(
    within(archivedSection).getByRole("button", {
      name: "Återställ: Ring receptionen",
    }),
  );
  expect(transport.restoreStepAction).toHaveBeenCalledWith(
    FIRST_ID,
    2,
    expect.stringMatching(KEY),
  );
  expect(transport.listStepActions).toHaveBeenCalledTimes(2);
  expect(
    await screen.findByRole("button", { name: "Arkivera: Ring receptionen" }),
  ).toHaveFocus();
  expect(
    screen.getByText("Återställde ”Ring receptionen”."),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Arkiverade (1)" }),
  ).not.toBeInTheDocument();
});

it("clears the move notice when the next write starts, so a refusal shows alone", async () => {
  const user = userEvent.setup();
  const transport = setup({
    archiveStepAction: vi.fn(() => Promise.reject(refusal("conflict"))),
  });
  await openActions(user, transport);

  await user.click(
    screen.getByRole("button", { name: "Flytta ned: Ring receptionen" }),
  );
  expect(
    await screen.findByText(manageLabelsSv.moved("Ring receptionen", 2, 2)),
  ).toBeInTheDocument();

  await user.click(
    screen.getByRole("button", { name: "Arkivera: Skicka mejlet" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    manageLabelsSv.conflict,
  );
  expect(
    screen.queryByText(manageLabelsSv.moved("Ring receptionen", 2, 2)),
  ).not.toBeInTheDocument();
});

it("shows the conflict message on a stale reorder and Read again reads the list again", async () => {
  const user = userEvent.setup();
  const transport = setup({
    reorderStepActions: vi.fn(() => Promise.reject(refusal("conflict"))),
  });
  await openActions(user, transport);

  await user.click(
    screen.getByRole("button", { name: "Flytta ned: Ring receptionen" }),
  );
  expect(await screen.findByText(manageLabelsSv.conflict)).toBeInTheDocument();
  expect(transport.listStepActions).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "Läs om" }));
  await waitFor(() =>
    expect(transport.listStepActions).toHaveBeenCalledTimes(2),
  );
  expect(screen.queryByText(manageLabelsSv.conflict)).not.toBeInTheDocument();
});

it("retries a failed reorder with the same idempotency key", async () => {
  const user = userEvent.setup();
  const reorder = vi
    .fn()
    .mockRejectedValueOnce(refusal("internal_error"))
    .mockImplementation((_stepId: string, items: WorkOrderItem[]) =>
      Promise.resolve(reordered(items)),
    );
  const transport = setup({
    reorderStepActions:
      reorder as unknown as WorkTransport["reorderStepActions"],
  });
  await openActions(user, transport);

  await user.click(
    screen.getByRole("button", { name: "Flytta ned: Ring receptionen" }),
  );
  expect(await screen.findByText(manageLabelsSv.failed)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Försök igen" }));
  expect(
    await screen.findByText("Flyttade ”Ring receptionen” till plats 2 av 2."),
  ).toBeInTheDocument();

  expect(reorder).toHaveBeenCalledTimes(2);
  expect(reorder.mock.calls[1]?.[2]).toBe(reorder.mock.calls[0]?.[2]);
});

it("shows a calm text when reading the actions is forbidden", async () => {
  const user = userEvent.setup();
  const transport = setup({
    listStepActions: vi.fn(() => Promise.reject(refusal("forbidden"))),
  });
  render(<ActionsHarness transport={transport} />);
  await user.click(screen.getByRole("button", { name: "Visa åtgärder" }));

  expect(
    await screen.findByText(stepActionsLabelsSv.forbidden),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("shows a failed read with Try again, which reads the list again", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockRejectedValueOnce(refusal("internal_error"))
    .mockResolvedValue(ORIGINAL);
  const transport = setup({
    listStepActions: list as unknown as WorkTransport["listStepActions"],
  });
  render(<ActionsHarness transport={transport} />);
  await user.click(screen.getByRole("button", { name: "Visa åtgärder" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Det gick inte att läsa. Försök igen.",
  );
  await user.click(screen.getByRole("button", { name: "Försök igen" }));
  expect(await screen.findByText("Ring receptionen")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps the English and Swedish key sets identical", () => {
  expect(Object.keys(stepActionsLabelsEn).sort()).toEqual(
    Object.keys(stepActionsLabelsSv).sort(),
  );
});
