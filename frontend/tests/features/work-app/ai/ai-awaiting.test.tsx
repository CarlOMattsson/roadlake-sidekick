import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { aiLabelsEn, aiLabelsSv } from "@/features/work-app/ai/ai-labels";
import { AwaitingApproval } from "@/features/work-app/ai/awaiting-approval";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
  type InlineSummaryLabels,
} from "@/features/work-app/inline/inline-summary-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { TaskSteps } from "@tests/helpers/steps-with-bar";
import type {
  WorkFrame,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import { aiStepEn, aiStepSv } from "@/features/mcp-apps/ui/ai-step-labels";
import {
  aiStep,
  aiTask,
  aiTransport,
  ownerStep,
  plan,
  reviewPlan,
  run,
  serverPlan,
} from "@tests/helpers/ai-plan-fixtures";
import { rootTask, taskA } from "@tests/helpers/work-app-fixtures";

/*
 * What an AI plan that waits for the owner says, and what stands after the owner's click: the inline Task card, the
 * AI Step's mark, the approval and answer lines, the cost line and the answer field's name. The views run in jsdom
 * with a simulated host; this is not a real Claude or Android host.
 */

const a = aiLabelsEn;

function inlineCard(
  task: WorkTask,
  getAiPlan: ReturnType<typeof vi.fn>,
  labels: InlineSummaryLabels = inlineSummaryLabelsEn,
) {
  const frame: WorkFrame = { kind: "task", id: task.id, task };
  const fullscreen = vi.fn();
  const work = {
    getTask: vi.fn().mockResolvedValue({ task }),
    updateTask: vi.fn(),
    getAiPlan,
  } as unknown as WorkTransport;
  render(
    <WorkView
      transport={work}
      initial={frame}
      labels={labels === inlineSummaryLabelsSv ? workSv : workEn}
      inlineLabels={labels}
      fullscreen={fullscreen}
    />,
  );
  return { fullscreen, work };
}

/* (a) The inline Task card */

it("says on the inline card that the plan waits for review, with the AI steps, and makes reviewing the primary", async () => {
  const user = userEvent.setup();
  const { fullscreen } = inlineCard(
    aiTask,
    vi.fn().mockResolvedValue({ plan: plan() }),
  );
  expect(await screen.findByText(a.planWaiting(1))).toBeInTheDocument();
  expect(a.planWaiting(1)).toBe("Plan waiting for review · 1 AI step");
  const review = screen.getByRole("button", { name: a.reviewPlan });
  expect(review).toHaveClass("sk-btn--primary");
  // Done stays, as the secondary; the plain Open is the review button.
  expect(
    screen.getByRole("button", { name: inlineSummaryLabelsEn.complete }),
  ).toHaveClass("sk-btn--secondary");
  expect(
    screen.queryByRole("button", { name: inlineSummaryLabelsEn.showTask }),
  ).toBeNull();
  await user.click(review);
  expect(fullscreen).toHaveBeenCalledTimes(1);
});

it("says it in Swedish on the inline card", async () => {
  inlineCard(
    aiTask,
    vi.fn().mockResolvedValue({ plan: plan() }),
    inlineSummaryLabelsSv,
  );
  expect(
    await screen.findByText("Plan väntar på granskning · 1 AI-steg"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: aiLabelsSv.reviewPlan }),
  ).toHaveClass("sk-btn--primary");
});

it("keeps the plain card when the plan is approved, absent, or the Task is not marked", async () => {
  const approved = vi
    .fn()
    .mockResolvedValue({ plan: plan({ state: "approved" }) });
  const { work } = inlineCard(aiTask, approved);
  await screen.findByRole("button", {
    name: inlineSummaryLabelsEn.complete,
  });
  await vi.waitFor(() => expect(approved).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("button", { name: a.reviewPlan })).toBeNull();
  expect(
    screen.getByRole("button", { name: inlineSummaryLabelsEn.complete }),
  ).toHaveClass("sk-btn--primary");
  expect(work.getTask).not.toHaveBeenCalled();
});

it("reads no plan for a Task that is not marked possible with AI", async () => {
  const getAiPlan = vi.fn();
  inlineCard({ ...aiTask, ai_possible: false }, getAiPlan);
  await screen.findByRole("button", { name: inlineSummaryLabelsEn.complete });
  expect(getAiPlan).not.toHaveBeenCalled();
});

/* (b) After the approval and after an answer */

it("tells who takes the next step after the approval, where the server runs no AI steps", async () => {
  const user = userEvent.setup();
  const approveAiPlan = vi.fn().mockResolvedValue({
    plan: plan({ state: "approved", approved_at: new Date().toISOString() }),
  });
  render(rootTask(aiTransport({ approveAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.approve }));
  const line = await screen.findByText(a.approvedNext);
  expect(line).toBeVisible();
  expect(line).not.toHaveClass("work-visually-hidden");
});

it("leaves the approval line to the run button where the server runs AI steps", async () => {
  const user = userEvent.setup();
  const approveAiPlan = vi.fn().mockResolvedValue({
    plan: serverPlan({ state: "approved" }),
  });
  render(
    rootTask(
      aiTransport({
        approveAiPlan,
        getAiPlan: vi
          .fn()
          .mockResolvedValue({ plan: plan({ server_runner: "available" }) }),
      }),
    ),
  );
  await user.click(await screen.findByRole("button", { name: a.approve }));
  expect(
    await screen.findByRole("button", { name: a.run }),
  ).toBeInTheDocument();
  expect(screen.queryByText(a.approvedNext)).toBeNull();
  expect(screen.getByText(a.approvedNow)).toHaveClass("work-visually-hidden");
});

function answering(runner: "off" | "available") {
  const question = run(
    { state: "needs_input", has_result: false, has_question: true },
    { question: "Which budget may I use?", result_text: null },
  );
  return aiTransport({
    getAiPlan: vi.fn().mockResolvedValue({
      plan: { ...reviewPlan("needs_input"), server_runner: runner },
    }),
    getAiStepRun: vi.fn().mockResolvedValue(question),
    reviewAiStepResult: vi
      .fn()
      .mockResolvedValue({ run: { ...question.run, state: "answered" } }),
  });
}

async function answer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: a.openRun.question }),
  );
  const region = await screen.findByRole("region", {
    name: a.resultFor(aiStep.title),
  });
  await user.click(within(region).getByRole("button", { name: a.answer }));
  await user.type(within(region).getByRole("textbox"), "Up to 5 USD");
  await user.click(within(region).getByRole("button", { name: a.answer }));
  return region;
}

it("tells who goes on after an answer, where the server runs no AI steps", async () => {
  const user = userEvent.setup();
  render(rootTask(answering("off")));
  const region = await answer(user);
  expect(await within(region).findByText(a.answeredNext)).toBeInTheDocument();
});

it("says only that the answer is sent where the server runs AI steps", async () => {
  const user = userEvent.setup();
  render(rootTask(answering("available")));
  const region = await answer(user);
  expect(
    await within(region).findByText(a.reviewed.answer),
  ).toBeInTheDocument();
  expect(within(region).queryByText(a.answeredNext)).toBeNull();
});

/* (c) The AI Step's mark before and after the approval */

function stepList(approved: boolean) {
  const steps = [ownerStep, { ...aiStep, ai_status: "ready" as const }];
  const work = aiTransport({}, steps);
  return render(
    <AwaitingApproval
      plan={plan(approved ? { state: "approved" } : { state: "draft" })}
    >
      <TaskSteps taskId={taskA.id} transport={work} labels={workEn} />
    </AwaitingApproval>,
  );
}

it("marks a ready AI Step as awaiting approval until the plan is approved", async () => {
  stepList(false);
  expect(
    await screen.findByRole("img", {
      name: "Performed by AI, awaiting approval",
    }),
  ).toHaveTextContent("AI · awaiting approval");
  expect(screen.queryByRole("img", { name: /, ready$/ })).toBeNull();
});

it("marks the AI Step ready once the plan is approved", async () => {
  stepList(true);
  expect(
    await screen.findByRole("img", { name: "Performed by AI, ready" }),
  ).toHaveTextContent("AI · ready");
});

it("says awaiting approval in Swedish and reads the owner as dig", () => {
  expect(aiStepSv.status.awaiting_approval).toBe("väntar på godkännande");
  expect(aiStepSv.reading(aiStepSv.performedBy.owner)).toBe("Görs av dig");
  expect(aiStepEn.reading(aiStepEn.performedBy.owner)).toBe("Performed by you");
});

/* (d) The cost line */

it("states the cost of the AI steps and the task's cap in a plain sentence, with the locale's numbers", () => {
  expect(a.budget("1.00 USD", "2.00 USD")).toBe(
    "Estimated cost of the AI steps: at most 1.00 USD (the task’s cap: 2.00 USD).",
  );
  expect(aiLabelsSv.budget("1,00 USD", "2,00 USD")).toBe(
    "Beräknad kostnad för AI-stegen: högst 1,00 USD (uppgiftens tak: 2,00 USD).",
  );
});

/* (e) The answer field's name */

it("names the answer field for a screen reader", async () => {
  const user = userEvent.setup();
  render(rootTask(answering("off")));
  await user.click(
    await screen.findByRole("button", { name: a.openRun.question }),
  );
  const region = await screen.findByRole("region", {
    name: a.resultFor(aiStep.title),
  });
  await user.click(within(region).getByRole("button", { name: a.answer }));
  const field = within(region).getByRole("textbox", { name: a.answerLabel });
  expect(field).toHaveAttribute("aria-label", a.answerLabel);
});
