import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { aiLabelsEn } from "@/features/work-app/ai/ai-labels";
import {
  aiStep,
  aiTransport,
  reviewPlan,
  run,
  RUN_ID,
} from "@tests/helpers/ai-plan-fixtures";
import { KEY, keyOf, rootTask } from "@tests/helpers/work-app-fixtures";
import type { WorkTransport } from "@/features/work-app/transport/transport";

/*
 * Reviewing the result of an AI Step in the Work room: open the run from the Step, then accept, redo, reject or answer.
 * The views run in jsdom with a simulated host; this is not a real Claude or Android host.
 */

const a = aiLabelsEn;
const REVIEWED = {
  run: run({ state: "accepted", version: 5 }).run,
  content: null,
};

/** A Task whose AI Step has a run waiting for the owner; `overrides` replace transport calls. */
function reviewing(
  overrides: Partial<WorkTransport> = {},
  state: "to_review" | "needs_input" = "to_review",
) {
  return aiTransport({
    getAiPlan: vi.fn().mockResolvedValue({ plan: reviewPlan(state) }),
    getAiStepRun: vi.fn().mockResolvedValue(run()),
    reviewAiStepResult: vi.fn().mockResolvedValue(REVIEWED),
    ...overrides,
  });
}

async function openRun(
  user: ReturnType<typeof userEvent.setup>,
  name: string = a.openRun.review,
) {
  await user.click(await screen.findByRole("button", { name }));
  return screen.findByRole("region", { name: a.resultFor(aiStep.title) });
}

/* 5. The four verdicts */

it("opens the run from the Step and shows the result with its model, cost and attempt", async () => {
  const user = userEvent.setup();
  const work = reviewing();
  render(rootTask(work));
  const region = await openRun(user);
  expect(work.getAiStepRun).toHaveBeenCalledWith(RUN_ID);
  expect(
    within(region).getByText("claude-test · 0.12 USD · attempt 1"),
  ).toBeInTheDocument();
  expect(
    within(region).getByText("Three prices: 100, 120, 140."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: a.openRun.review }),
  ).toHaveAttribute("aria-expanded", "true");
});

it("accepts the result at the run's version, then reads the plan and the Steps again", async () => {
  const user = userEvent.setup();
  const work = reviewing();
  render(rootTask(work));
  const region = await openRun(user);
  const plansBefore = vi.mocked(work.getAiPlan).mock.calls.length;
  const stepsBefore = vi.mocked(work.listTaskSteps).mock.calls.length;
  await user.click(within(region).getByRole("button", { name: a.accept }));
  expect(
    await within(region).findByText(a.reviewed.accept),
  ).toBeInTheDocument();
  expect(work.reviewAiStepResult).toHaveBeenCalledWith(
    RUN_ID,
    run().run.version,
    "accept",
    null,
    expect.stringMatching(KEY),
  );
  await waitFor(() =>
    expect(vi.mocked(work.getAiPlan).mock.calls.length).toBeGreaterThan(
      plansBefore,
    ),
  );
  await waitFor(() =>
    expect(vi.mocked(work.listTaskSteps).mock.calls.length).toBeGreaterThan(
      stepsBefore,
    ),
  );
  // The verdict is written once the buttons are gone: the run is no longer waiting for the owner.
  expect(within(region).queryByRole("button", { name: a.accept })).toBeNull();
});

it("redoes with a comment: the field opens first and the verdict carries the comment", async () => {
  const user = userEvent.setup();
  const work = reviewing();
  render(rootTask(work));
  const region = await openRun(user);
  await user.click(within(region).getByRole("button", { name: a.redo }));
  expect(work.reviewAiStepResult).not.toHaveBeenCalled();
  await user.type(
    within(region).getByLabelText(a.redoComment),
    "  Try cheaper shops  ",
  );
  await user.click(within(region).getByRole("button", { name: a.sendRedo }));
  expect(await within(region).findByText(a.reviewed.redo)).toBeInTheDocument();
  expect(work.reviewAiStepResult).toHaveBeenCalledWith(
    RUN_ID,
    run().run.version,
    "redo",
    "Try cheaper shops",
    expect.stringMatching(KEY),
  );
});

it("cancels a redo without writing", async () => {
  const user = userEvent.setup();
  const work = reviewing();
  render(rootTask(work));
  const region = await openRun(user);
  await user.click(within(region).getByRole("button", { name: a.redo }));
  await user.click(within(region).getByRole("button", { name: a.cancel }));
  expect(within(region).queryByLabelText(a.redoComment)).toBeNull();
  expect(within(region).getByRole("button", { name: a.accept })).toBeEnabled();
  expect(work.reviewAiStepResult).not.toHaveBeenCalled();
});

it("rejects the result with no comment", async () => {
  const user = userEvent.setup();
  const work = reviewing();
  render(rootTask(work));
  const region = await openRun(user);
  await user.click(within(region).getByRole("button", { name: a.reject }));
  expect(
    await within(region).findByText(a.reviewed.reject),
  ).toBeInTheDocument();
  expect(work.reviewAiStepResult).toHaveBeenCalledWith(
    RUN_ID,
    run().run.version,
    "reject",
    null,
    expect.stringMatching(KEY),
  );
});

it("answers a question: the answer is needed before it can be sent", async () => {
  const user = userEvent.setup();
  const question = run(
    { state: "needs_input", has_result: false, has_question: true },
    { question: "Which budget may I use?", result_text: null },
  );
  const work = reviewing(
    {
      getAiStepRun: vi.fn().mockResolvedValue(question),
      reviewAiStepResult: vi
        .fn()
        .mockResolvedValue({ run: { ...question.run, state: "answered" } }),
    },
    "needs_input",
  );
  render(rootTask(work));
  const region = await openRun(user, a.openRun.question);
  expect(
    within(region).getByText("Which budget may I use?"),
  ).toBeInTheDocument();
  expect(within(region).queryByRole("button", { name: a.accept })).toBeNull();
  await user.click(within(region).getByRole("button", { name: a.answer }));
  const send = within(region).getByRole("button", { name: a.answer });
  expect(send).toBeDisabled();
  await user.type(within(region).getByLabelText(a.answerLabel), "   ");
  expect(send).toBeDisabled();
  await user.type(within(region).getByLabelText(a.answerLabel), "Up to 5 USD");
  expect(send).toBeEnabled();
  await user.click(send);
  expect(await within(region).findByText(a.answeredNext)).toBeInTheDocument();
  expect(work.reviewAiStepResult).toHaveBeenCalledWith(
    RUN_ID,
    question.run.version,
    "answer",
    "Up to 5 USD",
    expect.stringMatching(KEY),
  );
});

it("retries a failed verdict with the same key", async () => {
  const user = userEvent.setup();
  const reviewAiStepResult = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue(REVIEWED);
  render(rootTask(reviewing({ reviewAiStepResult })));
  const region = await openRun(user);
  await user.click(within(region).getByRole("button", { name: a.accept }));
  expect(await within(region).findByText(a.reviewFailed)).toBeInTheDocument();
  await user.click(within(region).getByRole("button", { name: /try again/i }));
  expect(
    await within(region).findByText(a.reviewed.accept),
  ).toBeInTheDocument();
  expect(reviewAiStepResult).toHaveBeenCalledTimes(2);
  expect(keyOf(reviewAiStepResult, 1)).toBe(keyOf(reviewAiStepResult, 0));
});

it("reads the run again when the verdict meets a changed run", async () => {
  const user = userEvent.setup();
  const reviewAiStepResult = vi
    .fn()
    .mockRejectedValue(new HostToolError("conflict"));
  const work = reviewing({ reviewAiStepResult });
  render(rootTask(work));
  const region = await openRun(user);
  await user.click(within(region).getByRole("button", { name: a.accept }));
  const alert = await within(region).findByRole("alert");
  expect(within(alert).getByText(a.reviewConflict)).toBeInTheDocument();
  await user.click(within(alert).getByRole("button", { name: a.reload }));
  await waitFor(() => expect(work.getAiStepRun).toHaveBeenCalledTimes(2));
});

it("offers Try again when the run cannot be read", async () => {
  const user = userEvent.setup();
  const getAiStepRun = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue(run());
  render(rootTask(reviewing({ getAiStepRun })));
  await user.click(
    await screen.findByRole("button", { name: a.openRun.review }),
  );
  await user.click(await screen.findByRole("button", { name: /try again/i }));
  expect(
    await screen.findByText("Three prices: 100, 120, 140."),
  ).toBeInTheDocument();
  expect(getAiStepRun).toHaveBeenCalledTimes(2);
});

it("draws no opener for an AI Step without a run to look at", async () => {
  const work = aiTransport();
  render(rootTask(work));
  await screen.findByText(a.draft);
  expect(screen.queryByRole("button", { name: a.openRun.review })).toBeNull();
  expect(screen.queryByRole("button", { name: a.openRun.look })).toBeNull();
});

/* 6. Safe text */

it("draws the result as literal text: no image, link or markup is made of it", async () => {
  const user = userEvent.setup();
  const hostile =
    '<img src="x" onerror="alert(1)"> [länk](https://example.test) <a href="https://example.test">a</a>';
  const work = reviewing({
    getAiStepRun: vi
      .fn()
      .mockResolvedValue(
        run({}, { result_text: hostile, result_summary: "<b>sum</b>" }),
      ),
  });
  const { container } = render(rootTask(work));
  await openRun(user);
  expect(screen.getByText(hostile)).toBeInTheDocument();
  expect(screen.getByText("<b>sum</b>")).toBeInTheDocument();
  const shown = container.querySelector(".work-ai-run") as HTMLElement;
  expect(shown.querySelector("img")).toBeNull();
  expect(shown.querySelector("a")).toBeNull();
  expect(shown.querySelector("b")).toBeNull();
});

it("folds a long result and unfolds it on request", async () => {
  const user = userEvent.setup();
  const long = "x".repeat(400);
  const work = reviewing({
    getAiStepRun: vi.fn().mockResolvedValue(run({}, { result_text: long })),
  });
  render(rootTask(work));
  const region = await openRun(user);
  const text = within(region).getByText(long);
  expect(text).toHaveClass("work-ai-text--clamped");
  await user.click(within(region).getByRole("button", { name: a.showAll }));
  expect(text).not.toHaveClass("work-ai-text--clamped");
  expect(
    within(region).getByRole("button", { name: a.showLess }),
  ).toBeInTheDocument();
});

it("tells how many of the reported actions are done and what the owner wrote earlier", async () => {
  const user = userEvent.setup();
  const work = reviewing({
    getAiStepRun: vi.fn().mockResolvedValue(
      run(
        {},
        {
          checklist: [
            { action_id: "a1", done: true },
            { action_id: "a2", done: false },
          ],
          comment: "Check VAT",
        },
      ),
    ),
  });
  render(rootTask(work));
  const region = await openRun(user);
  expect(within(region).getByText(a.checklist(1, 2))).toBeInTheDocument();
  expect(within(region).getByText(/Your comment:/)).toHaveTextContent(
    "Your comment: Check VAT",
  );
});
