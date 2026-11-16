import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { aiLabelsEn } from "@/features/work-app/ai/ai-labels";
import type { WorkTransport } from "@/features/work-app/transport/transport";
import {
  aiStep,
  aiTransport,
  DIGEST,
  ownerStep,
  RUN_ID,
  runRecord,
  serverPlan,
  serverRun,
} from "@tests/helpers/ai-plan-fixtures";
import { KEY, keyOf, rootTask, taskA } from "@tests/helpers/work-app-fixtures";

/*
 * Running an approved AI plan on the server from the Work room: "Kör nästa steg", the queued and running line with
 * "Avbryt", the background reads that bring the result to review, the refusals and what AI costs. The views run in
 * jsdom with a simulated host; this is not a real Claude or Android host.
 */

const a = aiLabelsEn;
const readySteps = [ownerStep, { ...aiStep, ai_status: "ready" as const }];

function serving(overrides: Partial<WorkTransport> = {}) {
  return aiTransport(
    {
      getAiPlan: vi.fn().mockResolvedValue({ plan: serverPlan() }),
      ...overrides,
    },
    readySteps,
  );
}

afterEach(() => {
  vi.useRealTimers();
  document.head.querySelector('meta[name="sidekick-ai-usage"]')?.remove();
});

/* 1. Nothing with the server runner off */

it("draws no Run button and no cost where the server runner is off", async () => {
  const user = userEvent.setup();
  const off = serverPlan({
    server_runner: "off",
    task_spent_usd: 0.4,
    month_spent_usd: 3,
  });
  render(
    rootTask(serving({ getAiPlan: vi.fn().mockResolvedValue({ plan: off }) })),
  );
  await user.click(await screen.findByRole("button", { name: a.showSteps(2) }));
  expect(
    screen.getByText(a.budget("0.50 USD", "2.00 USD")),
  ).toBeInTheDocument();
  expect(screen.queryByText(/used so far/)).toBeNull();
  expect(screen.queryByText(/AI this month/)).toBeNull();
  expect(screen.queryByRole("button", { name: a.run })).toBeNull();
});

it("draws no Run button when the next Step is not one the server may run", async () => {
  render(
    rootTask(
      serving({
        getAiPlan: vi.fn().mockResolvedValue({
          plan: serverPlan({}, { server_startable: false }),
        }),
      }),
    ),
  );
  expect(
    await screen.findByRole("button", { name: a.showSteps(2) }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.run })).toBeNull();
});

it("draws no Run button when the host does not answer run_ai_plan", async () => {
  render(
    rootTask(
      serving({ supportsTool: (name: string) => name !== "run_ai_plan" }),
    ),
  );
  expect(
    await screen.findByRole("button", { name: a.showSteps(2) }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.run })).toBeNull();
});

/* 2. Run, the queued line and Avbryt */

it("runs the next Step at the digest it read, then shows it queued with Avbryt", async () => {
  const user = userEvent.setup();
  const queued = serverPlan(
    {},
    {
      ai_status: "running",
      server_startable: false,
      latest_run: serverRun("queued"),
    },
  );
  const runAiPlan = vi.fn().mockResolvedValue({ plan: queued });
  const work = serving({ runAiPlan });
  render(rootTask(work));
  await user.click(await screen.findByRole("button", { name: a.run }));
  expect(runAiPlan).toHaveBeenCalledWith(
    taskA.id,
    DIGEST,
    expect.stringMatching(KEY),
  );
  expect(await screen.findByText(a.runState.queued)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: a.cancelRunFor(aiStep.title) }),
  ).toBeInTheDocument();
  // No second run while one is under way.
  expect(screen.queryByRole("button", { name: a.run })).toBeNull();
  // The Step marks follow: the Steps are read again.
  await waitFor(() => expect(work.listTaskSteps).toHaveBeenCalledTimes(2));
});

it("says Run again when the next Step failed before", async () => {
  render(
    rootTask(
      serving({
        getAiPlan: vi.fn().mockResolvedValue({
          plan: serverPlan(
            {},
            {
              ai_status: "failed",
              latest_run: runRecord({
                runner: "server",
                state: "failed",
                has_result: false,
                failure_category: "model_error",
              }),
            },
          ),
        }),
      }),
    ),
  );
  expect(
    await screen.findByRole("button", { name: a.runAgain }),
  ).toBeInTheDocument();
});

it("cancels the run at its version and reads the plan again", async () => {
  const user = userEvent.setup();
  const running = serverPlan(
    {},
    {
      ai_status: "running",
      server_startable: false,
      latest_run: serverRun("running", { version: 3 }),
    },
  );
  const getAiPlan = vi
    .fn()
    .mockResolvedValueOnce({ plan: running })
    .mockResolvedValue({ plan: serverPlan({}, { ai_status: "ready" }) });
  const cancelAiStepRun = vi.fn().mockResolvedValue({
    run: serverRun("running", { state: "cancelled", version: 4 }),
  });
  render(rootTask(serving({ getAiPlan, cancelAiStepRun })));
  expect(await screen.findByText(a.runState.running)).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: a.cancelRunFor(aiStep.title) }),
  );
  expect(cancelAiStepRun).toHaveBeenCalledWith(
    RUN_ID,
    3,
    expect.stringMatching(KEY),
  );
  expect(
    await screen.findByRole("button", { name: a.run }),
  ).toBeInTheDocument();
  expect(screen.queryByText(a.runState.running)).toBeNull();
});

it("retries a failed cancel with the same key", async () => {
  const user = userEvent.setup();
  const running = serverPlan(
    {},
    {
      ai_status: "running",
      server_startable: false,
      latest_run: serverRun("running"),
    },
  );
  const cancelAiStepRun = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue({ run: serverRun("running", { state: "cancelled" }) });
  render(
    rootTask(
      serving({
        getAiPlan: vi.fn().mockResolvedValue({ plan: running }),
        cancelAiStepRun,
      }),
    ),
  );
  await user.click(
    await screen.findByRole("button", { name: a.cancelRunFor(aiStep.title) }),
  );
  expect(await screen.findByText(a.cancelFailed)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /try again/i }));
  await waitFor(() => expect(cancelAiStepRun).toHaveBeenCalledTimes(2));
  expect(keyOf(cancelAiStepRun, 1)).toBe(keyOf(cancelAiStepRun, 0));
});

it("offers no Avbryt when the host does not answer cancel_ai_step_run", async () => {
  render(
    rootTask(
      serving({
        supportsTool: (name: string) => name !== "cancel_ai_step_run",
        getAiPlan: vi.fn().mockResolvedValue({
          plan: serverPlan(
            {},
            { ai_status: "running", latest_run: serverRun("queued") },
          ),
        }),
      }),
    ),
  );
  expect(await screen.findByText(a.runState.queued)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: a.cancelRunFor(aiStep.title) }),
  ).toBeNull();
});

/* 3. The result turns up without a message to Claude */

it("reads the plan again while the run is under way and offers the result to review", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const running = serverPlan(
    {},
    {
      ai_status: "running",
      server_startable: false,
      latest_run: serverRun("running"),
    },
  );
  const done = serverPlan(
    { task_spent_usd: 0.12 },
    {
      ai_status: "to_review",
      server_startable: false,
      latest_run: runRecord({ runner: "server", state: "to_review" }),
    },
  );
  const getAiPlan = vi
    .fn()
    .mockResolvedValueOnce({ plan: running })
    .mockResolvedValueOnce({ plan: running })
    .mockResolvedValue({ plan: done });
  const work = serving({ getAiPlan });
  render(rootTask(work));
  expect(await screen.findByText(a.runState.running)).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(4_000));
  expect(getAiPlan).toHaveBeenCalledTimes(2);
  expect(screen.getByText(a.runState.running)).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(4_000));
  expect(
    await screen.findByRole("button", { name: a.openRun.review }),
  ).toBeInTheDocument();
  expect(screen.queryByText(a.runState.running)).toBeNull();
  expect(screen.getByText(a.runFinished(aiStep.title))).toBeInTheDocument();
  // Nothing more to watch: no further reads.
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(getAiPlan).toHaveBeenCalledTimes(3);
});

it("keeps watching through a failed background read", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const queued = serverPlan(
    {},
    {
      ai_status: "running",
      server_startable: false,
      latest_run: serverRun("queued"),
    },
  );
  const getAiPlan = vi
    .fn()
    .mockResolvedValueOnce({ plan: queued })
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue({ plan: queued });
  render(rootTask(serving({ getAiPlan })));
  expect(await screen.findByText(a.runState.queued)).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(4_000));
  await act(() => vi.advanceTimersByTimeAsync(4_000));
  expect(getAiPlan).toHaveBeenCalledTimes(3);
  // The plan stays on screen; no error replaces it.
  expect(screen.getByText(a.runState.queued)).toBeInTheDocument();
});

/* 4. Refusals: one calm line under the Step */

for (const reason of ["ai_budget_reached", "ai_limit_reached"] as const)
  it(`says ${reason} under the Step and drops the Run button`, async () => {
    const user = userEvent.setup();
    const runAiPlan = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict", reason));
    render(rootTask(serving({ runAiPlan })));
    await user.click(await screen.findByRole("button", { name: a.run }));
    expect(await screen.findByText(a.runRefused[reason])).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: a.run })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

it("reads the plan again when the server runner was turned off meanwhile", async () => {
  const user = userEvent.setup();
  const getAiPlan = vi
    .fn()
    .mockResolvedValueOnce({ plan: serverPlan() })
    .mockResolvedValue({ plan: serverPlan({ server_runner: "off" }) });
  const runAiPlan = vi
    .fn()
    .mockRejectedValue(new HostToolError("conflict", "ai_runner_off"));
  render(rootTask(serving({ getAiPlan, runAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.run }));
  expect(
    await screen.findByText(a.runRefused.ai_runner_off),
  ).toBeInTheDocument();
  await waitFor(() => expect(getAiPlan).toHaveBeenCalledTimes(2));
});

it("reads the plan again, quietly, when it changed since it was read", async () => {
  const user = userEvent.setup();
  const getAiPlan = vi.fn().mockResolvedValue({ plan: serverPlan() });
  const runAiPlan = vi
    .fn()
    .mockRejectedValue(new HostToolError("conflict", "plan_changed"));
  render(rootTask(serving({ getAiPlan, runAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.run }));
  await waitFor(() => expect(getAiPlan).toHaveBeenCalledTimes(2));
  for (const text of Object.values(a.runRefused))
    expect(screen.queryByText(text)).toBeNull();
  expect(screen.getByRole("button", { name: a.run })).toBeInTheDocument();
});

it("retries a run that failed in transit with the same key", async () => {
  const user = userEvent.setup();
  const runAiPlan = vi
    .fn()
    .mockRejectedValueOnce(new Error("down"))
    .mockResolvedValue({
      plan: serverPlan(
        {},
        {
          ai_status: "running",
          server_startable: false,
          latest_run: serverRun("queued"),
        },
      ),
    });
  render(rootTask(serving({ runAiPlan })));
  await user.click(await screen.findByRole("button", { name: a.run }));
  expect(await screen.findByText(a.runRefused.failed)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /try again/i }));
  expect(await screen.findByText(a.runState.queued)).toBeInTheDocument();
  expect(keyOf(runAiPlan, 1)).toBe(keyOf(runAiPlan, 0));
});

/* 5. What AI costs stays folded */

it("adds the Task's cost to the folded budget only once it is above zero", async () => {
  const user = userEvent.setup();
  render(
    rootTask(
      serving({
        getAiPlan: vi
          .fn()
          .mockResolvedValue({ plan: serverPlan({ task_spent_usd: 0.12 }) }),
      }),
    ),
  );
  expect(
    await screen.findByRole("button", { name: a.run }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/used so far/)).toBeNull();
  await user.click(screen.getByRole("button", { name: a.showSteps(2) }));
  expect(
    screen.getByText(
      `${a.budget("0.50 USD", "2.00 USD")} ${a.spent("0.12 USD")}`,
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/AI this month/)).toBeNull();
});

it("shows the month's AI cost only where the instance shows AI cost", async () => {
  const user = userEvent.setup();
  const meta = document.createElement("meta");
  meta.name = "sidekick-ai-usage";
  meta.content = "on";
  document.head.append(meta);
  render(
    rootTask(
      serving({
        getAiPlan: vi
          .fn()
          .mockResolvedValue({ plan: serverPlan({ month_spent_usd: 1.2 }) }),
      }),
    ),
  );
  await user.click(await screen.findByRole("button", { name: a.showSteps(2) }));
  expect(
    screen.getByText(a.month("1.20 USD", "50.00 USD")),
  ).toBeInTheDocument();
  // A Task that has cost nothing says nothing about it.
  expect(screen.queryByText(/used so far/)).toBeNull();
});
