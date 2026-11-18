import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { aiLabelsEn, aiLabelsSv } from "@/features/work-app/ai/ai-labels";
import { RoomMessageContext } from "@/features/mcp-apps/ui/room-context";
import { workEn } from "@/features/work-app/shared/labels";
import {
  aiStep,
  aiTask,
  aiTransport,
  DIGEST,
  NEW_DIGEST,
  noPlan,
  ownerStep,
  plan,
} from "@tests/helpers/ai-plan-fixtures";
import {
  KEY,
  keyOf,
  projectA,
  projectTask,
  rootProject,
  rootTask,
  taskA,
  transport,
} from "@tests/helpers/work-app-fixtures";

/*
 * The AI plan of a Task in the Work room: the mark in the menu and on the row, the plan card, its approval and the
 * Step marks. The views run in jsdom with a simulated host; this is not a real Claude or Android host.
 */

const a = aiLabelsEn;

function withSend(
  send = vi.fn().mockResolvedValue(true),
  work = aiTransport(),
) {
  return {
    send,
    work,
    ui: (
      <RoomMessageContext.Provider value={send}>
        {rootTask(work)}
      </RoomMessageContext.Provider>
    ),
  };
}

async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
}

/* 1. The mark */

it("marks the Task as possible with AI from the ⋯ menu", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...taskA, ai_possible: true, version: 2 } });
  render(
    rootTask(
      transport({
        updateTask,
        getAiPlan: vi.fn().mockResolvedValue({ plan: noPlan() }),
      }),
    ),
  );
  await openMenu(user);
  const entry = screen.getByRole("button", { name: a.possible });
  expect(entry).toHaveAttribute("aria-pressed", "false");
  await user.click(entry);
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { ai_possible: true },
    expect.stringMatching(KEY),
  );
});

it("shows the menu entry pressed and clears the mark when the Task is marked", async () => {
  const user = userEvent.setup();
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...aiTask, ai_possible: false, version: 2 } });
  render(
    rootTask(
      aiTransport({
        updateTask,
        getAiPlan: vi.fn().mockResolvedValue({ plan: noPlan() }),
      }),
    ),
  );
  await openMenu(user);
  const entry = screen.getByRole("button", { name: a.possible });
  expect(entry).toHaveAttribute("aria-pressed", "true");
  await user.click(entry);
  await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  expect(updateTask).toHaveBeenCalledWith(
    taskA.id,
    1,
    { ai_possible: false },
    expect.stringMatching(KEY),
  );
});

it("offers the mark only when the host answers update_task with ai_possible", async () => {
  const user = userEvent.setup();
  render(
    rootTask(
      transport({
        supportsCall: (name: string, args: object) =>
          !(
            name === "update_task" &&
            "changes" in args &&
            JSON.stringify(args.changes).includes("ai_possible")
          ),
      }),
    ),
  );
  await openMenu(user);
  expect(screen.queryByRole("button", { name: a.possible })).toBeNull();
});

it("draws the AI mark on a Task's row in a Project when the Task is marked", async () => {
  const work = transport({
    listProjectTasks: vi.fn().mockResolvedValue({
      items: [
        {
          id: projectTask.id,
          title: projectTask.title,
          status: projectTask.status,
          due_at: null,
          ai_possible: true,
        },
        {
          id: taskA.id,
          title: taskA.title,
          status: "todo",
          due_at: null,
        },
      ],
      next_cursor: null,
    }),
  });
  render(rootProject(work, projectA.id));
  await screen.findByText(projectTask.title);
  expect(screen.getAllByRole("img", { name: a.possible })).toHaveLength(1);
});

/* 2. No plan */

it("says there is no plan and asks Claude to plan with the title and the id", async () => {
  const user = userEvent.setup();
  const { send, ui } = withSend(
    undefined,
    aiTransport({ getAiPlan: vi.fn().mockResolvedValue({ plan: noPlan() }) }),
  );
  render(ui);
  expect(await screen.findByText(a.none)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: a.askPlan }));
  expect(send).toHaveBeenCalledTimes(1);
  const text = send.mock.calls[0]?.[0] as string;
  expect(text).toContain(taskA.title);
  expect(text).toContain(taskA.id);
});

it("draws no ask button without the host's messages", async () => {
  render(
    rootTask(
      aiTransport({ getAiPlan: vi.fn().mockResolvedValue({ plan: noPlan() }) }),
    ),
  );
  expect(await screen.findByText(a.none)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.askPlan })).toBeNull();
});

it("reads no plan for a Task that is not marked", async () => {
  const work = transport();
  render(rootTask(work));
  await screen.findByRole("heading", { name: taskA.title });
  expect(work.getAiPlan).not.toHaveBeenCalled();
  expect(screen.queryByRole("heading", { name: a.heading })).toBeNull();
});

/* 3. A draft */

it("shows the draft's Steps with who does them and opens an AI Step to what it will do", async () => {
  const user = userEvent.setup();
  render(rootTask(aiTransport()));
  const card = (await screen.findByRole("heading", { name: a.heading }))
    .parentElement as HTMLElement;
  expect(await within(card).findByText(a.draft)).toBeInTheDocument();
  expect(within(card).getByText(ownerStep.title)).toBeInTheDocument();
  expect(
    within(card).getByRole("img", { name: "Performed by you" }),
  ).toBeInTheDocument();
  expect(
    within(card).getByRole("img", { name: "Performed by AI" }),
  ).toBeInTheDocument();
  expect(
    within(card).queryByText("Find three prices for the service"),
  ).toBeNull();
  await user.click(
    within(card).getByRole("button", { name: a.detailsFor(aiStep.title) }),
  );
  expect(
    within(card).getByText("Find three prices for the service"),
  ).toBeInTheDocument();
  expect(
    within(card).getByText(a.doneWhen(["three prices are found"])),
  ).toBeInTheDocument();
  expect(
    within(card).getByText(a.tools(["web search", "the task’s text"])),
  ).toBeInTheDocument();
  expect(
    within(card).getByText(a.output("checklist", "4,000")),
  ).toBeInTheDocument();
  expect(
    within(card).getByText("Asks you about the budget."),
  ).toBeInTheDocument();
  expect(within(card).getByText(a.stepBudget("0.50 USD"))).toBeInTheDocument();
  expect(
    within(card).getByText(a.budget("0.50 USD", "2.00 USD")),
  ).toBeInTheDocument();
});

it("approves exactly the digest it read, then shows the approval time and drops the button", async () => {
  const user = userEvent.setup();
  const approvedAt = new Date().toISOString();
  const approveAiPlan = vi.fn().mockResolvedValue({
    plan: plan({ state: "approved", approved_at: approvedAt }),
  });
  const work = aiTransport({ approveAiPlan });
  render(rootTask(work));
  await user.click(await screen.findByRole("button", { name: a.approve }));
  expect(approveAiPlan).toHaveBeenCalledWith(
    taskA.id,
    DIGEST,
    expect.stringMatching(KEY),
  );
  expect(await screen.findByText(/^Approved \d{2}:\d{2}$/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.approve })).toBeNull();
  expect(screen.getByText(a.approvedNext)).toBeInTheDocument();
});

it("retries a failed approval with the same key", async () => {
  const user = userEvent.setup();
  const approveAiPlan = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue({
      plan: plan({ state: "approved", approved_at: new Date().toISOString() }),
    });
  render(rootTask(aiTransport({ approveAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.approve }));
  expect(await screen.findByText(a.approveFailed)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /try again/i }));
  expect(await screen.findByText(/^Approved \d{2}:\d{2}$/)).toBeInTheDocument();
  expect(approveAiPlan).toHaveBeenCalledTimes(2);
  expect(keyOf(approveAiPlan, 1)).toBe(keyOf(approveAiPlan, 0));
});

it("offers no approval when the host does not answer approve_ai_plan", async () => {
  render(
    rootTask(
      aiTransport({
        supportsTool: (name: string) => name !== "approve_ai_plan",
      }),
    ),
  );
  expect(await screen.findByText(a.draft)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.approve })).toBeNull();
});

it("says a plan is approved on one line with its Steps folded, and unfolds them", async () => {
  const user = userEvent.setup();
  render(
    rootTask(
      aiTransport({
        getAiPlan: vi.fn().mockResolvedValue({
          plan: plan({
            state: "approved",
            approved_at: new Date().toISOString(),
          }),
        }),
      }),
    ),
  );
  const fold = await screen.findByRole("button", { name: a.showSteps(2) });
  expect(screen.queryByText(a.budget("0.50 USD", "2.00 USD"))).toBeNull();
  await user.click(fold);
  expect(
    screen.getByText(a.budget("0.50 USD", "2.00 USD")),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: a.hideSteps })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});

it("asks Claude to change the plan", async () => {
  const user = userEvent.setup();
  const { send, ui } = withSend();
  render(ui);
  await user.click(await screen.findByRole("button", { name: a.change }));
  const text = send.mock.calls[0]?.[0] as string;
  expect(text).toContain(taskA.title);
  expect(text).toContain(taskA.id);
});

/* 4. A plan changed after its approval */

it("asks for a new approval when the plan changed since the approval", async () => {
  render(
    rootTask(
      aiTransport({
        getAiPlan: vi.fn().mockResolvedValue({
          plan: plan({
            state: "changed_since_approval",
            approved_at: "2026-11-15T08:00:00Z",
          }),
        }),
      }),
    ),
  );
  expect(await screen.findByText(a.changed)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: a.approve })).toBeEnabled();
});

it("reads the plan again after a conflicting approval and approves the new digest", async () => {
  const user = userEvent.setup();
  const getAiPlan = vi
    .fn()
    .mockResolvedValueOnce({ plan: plan() })
    .mockResolvedValue({ plan: plan({ digest: NEW_DIGEST }) });
  const approveAiPlan = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({
      plan: plan({ state: "approved", approved_at: new Date().toISOString() }),
    });
  render(rootTask(aiTransport({ getAiPlan, approveAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.approve }));
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText(a.approveConflict)).toBeInTheDocument();
  await user.click(within(alert).getByRole("button", { name: a.reload }));
  await waitFor(() => expect(getAiPlan).toHaveBeenCalledTimes(2));
  await user.click(await screen.findByRole("button", { name: a.approve }));
  await waitFor(() => expect(approveAiPlan).toHaveBeenCalledTimes(2));
  expect(approveAiPlan.mock.calls[1]?.[1]).toBe(NEW_DIGEST);
  // A new click starts over with a new key.
  expect(keyOf(approveAiPlan, 1)).not.toBe(keyOf(approveAiPlan, 0));
});

it("says nothing from the backend when the approval is forbidden", async () => {
  const user = userEvent.setup();
  const approveAiPlan = vi
    .fn()
    .mockRejectedValue(new HostToolError("forbidden"));
  render(rootTask(aiTransport({ approveAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.approve }));
  expect(await screen.findByText(a.approveForbidden)).toBeInTheDocument();
});

it("offers Try again when the plan cannot be read", async () => {
  const user = userEvent.setup();
  const getAiPlan = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue({ plan: plan() });
  render(rootTask(aiTransport({ getAiPlan })));
  await user.click(await screen.findByRole("button", { name: /try again/i }));
  expect(await screen.findByText(a.draft)).toBeInTheDocument();
  expect(getAiPlan).toHaveBeenCalledTimes(2);
});

/* 7. Language parity */

it("keeps the Swedish and English words in step, nested objects included", () => {
  const shape = (value: unknown): unknown =>
    typeof value === "object" && value !== null
      ? Object.fromEntries(
          Object.entries(value).map(([key, inner]) => [key, shape(inner)]),
        )
      : typeof value;
  expect(Object.keys(aiLabelsSv)).toEqual(Object.keys(aiLabelsEn));
  expect(shape(aiLabelsSv)).toEqual(shape(aiLabelsEn));
  for (const key of ["capability", "reviewed", "openRun"] as const)
    expect(Object.keys(aiLabelsSv[key])).toEqual(Object.keys(aiLabelsEn[key]));
  // Swedish is not a copy of the English words.
  expect(aiLabelsSv.possible).not.toBe(aiLabelsEn.possible);
});

/* 8. The Step mark */

it("marks who does each Step in a Task with an AI Step, and where the AI Step stands", async () => {
  render(rootTask(aiTransport()));
  const row = await screen.findByText(
    (_, node) =>
      node?.tagName === "SPAN" &&
      node.textContent?.startsWith(aiStep.title) === true,
    { selector: ".work-steps span" },
  );
  const list = row.closest("ul") as HTMLElement;
  expect(
    within(list).getByRole("img", { name: "Performed by AI, to review" }),
  ).toBeInTheDocument();
  expect(
    within(list).getByRole("img", { name: "Performed by you" }),
  ).toBeInTheDocument();
});

it("draws no Step marks in a Task without an AI Step", async () => {
  const work = transport({
    listTaskSteps: vi.fn().mockResolvedValue({
      items: [ownerStep, { ...ownerStep, id: "other", title: "Skriv" }],
      next_cursor: null,
    }),
  });
  render(rootTask(work));
  await screen.findByText(ownerStep.title);
  expect(screen.queryByRole("img", { name: /Performed by/ })).toBeNull();
});
