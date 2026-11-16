import { expect, test, type Locator, type Page } from "@playwright/test";
import { domainReplies, ids, ok, task } from "./sidekick-domain-fixtures";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  setHostReply,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// Running an approved AI plan on the server from a Task, in a real Chromium on the simulated host (mcp-host-fixture.ts),
// not a real Claude or Android host: "Kör nästa steg", the queued line with Avbryt, the background read that brings the
// result to review, a refusal, and what AI costs folded with the Steps. Swedish and English, 320 and 412 px, light and
// dark.

/** Set it to a folder to also write a screenshot of every case there. */
const SHOTS = process.env.AI_RUN_SHOTS_DIR;
const SHOWN = '<meta name="sidekick-ai-usage" content="on">';

const stepId = (n: number) => `019f0000-0000-7000-8000-0000000000b${n}`;
const aiTask = { ...task, ai_possible: true };
const owner = {
  id: stepId(1),
  title: "Ta fram förra årets avtal",
  status: "completed",
  due_at: null,
  version: 1,
  position: 1,
  performer: "owner",
  ai_status: null,
};
const ai = {
  id: stepId(2),
  title: "Jämför priset med offerten från Bergström Bygg",
  status: "todo",
  due_at: null,
  version: 1,
  position: 2,
  performer: "ai",
  ai_status: "ready",
};
const spec = {
  spec_version: 1,
  goal: "Jämför offerten med förra årets avtal.",
  done_when: ["varje post har ett pris"],
  capabilities: ["read_task_context"],
  context: { include_contacts: false, include_references: false },
  output: { format: "table", max_chars: 4000 },
  budget: { max_usd: 0.5, max_turns: 8 },
  stop_and_ask: [],
  effects: "none",
  privacy: "normal",
  runner: "any",
};

function run(state: string) {
  return {
    id: "019f0000-0000-7000-8000-0000000000c1",
    task_id: ids.task,
    step_id: ai.id,
    attempt: 1,
    state,
    runner: "server",
    model: "claude-sonnet-4-5",
    cost_usd: state === "to_review" ? 0.08 : 0,
    cost_source: "provider",
    input_tokens: 0,
    output_tokens: 0,
    has_result: state === "to_review",
    has_question: false,
    failure_category: null,
    created_at: "2026-11-16T08:00:00Z",
    started_at: state === "queued" ? null : "2026-11-16T08:00:05Z",
    finished_at: null,
    reviewed_at: null,
    lease_until: null,
    version: 1,
  };
}

function steps(aiStatus: string) {
  return { items: [owner, { ...ai, ai_status: aiStatus }], next_cursor: null };
}

function plan(aiStatus: string, latest: unknown, startable = false) {
  return {
    plan: {
      task_id: ids.task,
      task_version: 1,
      task_title: task.title,
      ai_possible: true,
      state: "approved",
      digest: "a".repeat(64),
      approved_at: "2026-11-16T07:02:00Z",
      task_cap_usd: 2,
      task_spent_usd: 0.12,
      month_spent_usd: 1.2,
      month_cap_usd: 50,
      server_runner: "available",
      steps: [owner, { ...ai, ai_status: aiStatus }].map((step, index) => ({
        step: {
          ...step,
          task_id: ids.task,
          instruction: null,
          archived_at: null,
          attention_requested: false,
        },
        ai_spec: index === 1 ? spec : null,
        action_titles: [],
        ai_status: step.ai_status,
        attempts: latest ? 1 : 0,
        latest_run: index === 1 ? latest : null,
        server_startable: index === 1 && startable,
      })),
    },
  };
}

const words = {
  sv: {
    run: "Kör nästa steg",
    fold: "Visa stegen (2)",
    queued: "I kö på servern",
    cancel: `Avbryt körningen av ${ai.title}`,
    review: "Granska resultatet",
    spent: "0,12 USD använt hittills.",
    month: "AI denna månad: 1,20 USD av 50,00 USD.",
    budget: "Kostnadstaket är nått, så steget körs inte nu.",
  },
  en: {
    run: "Run the next step",
    fold: "Show the steps (2)",
    queued: "Queued on the server",
    cancel: `Cancel the run of ${ai.title}`,
    review: "Review the result",
    spent: "0.12 USD used so far.",
    month: "AI this month: 1.20 USD of 50.00 USD.",
    budget: "The cost cap is reached, so the step will not run now.",
  },
};

async function openTask(
  page: Page,
  options: {
    locale: "sv" | "en";
    width: number;
    theme: "light" | "dark";
    replies?: Record<string, unknown>;
  },
) {
  await page.emulateMedia({ colorScheme: options.theme });
  const html = readBuiltApp("sidekick", options.locale);
  const { app, failures } = await openSimulatedApp(page, {
    resource: html.replace("<head>", `<head>${SHOWN}`),
    width: options.width,
    height: 780,
    hostContext: {
      locale: options.locale,
      theme: options.theme,
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: "get_task" } },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: {
      ...domainReplies(),
      get_task: ok({ task: aiTask }),
      list_task_steps: ok(steps("ready")),
      get_ai_plan: ok(plan("ready", null, true)),
      run_ai_plan: ok(plan("running", run("queued"))),
      ...options.replies,
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { task: aiTask });
  return { app, failures };
}

/** The target a finger gets is at least 44 × 44, and the control stands whole inside the view. */
async function expectTappable(control: Locator) {
  const target = await effectiveTargetSize(control);
  expect(target!.width).toBeGreaterThanOrEqual(44);
  expect(target!.height).toBeGreaterThanOrEqual(44);
  expect(
    await control.evaluate(
      (el) =>
        el.getBoundingClientRect().right <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

async function shoot(page: Page, file: string, at: Locator) {
  if (!SHOTS) return;
  await at.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/${file}.png` });
}

for (const locale of ["sv", "en"] as const)
  for (const width of [320, 412])
    for (const theme of ["light", "dark"] as const)
      test(`runs the next AI Step on the server and brings its result to review (${locale}, ${width} px, ${theme})`, async ({
        page,
      }) => {
        const w = words[locale];
        const { app, failures } = await openTask(page, {
          locale,
          width,
          theme,
        });
        const runButton = app.getByRole("button", { name: w.run });
        await expect(runButton).toBeVisible();
        await expectTappable(runButton);
        // What AI costs stands only among the folded Steps.
        await expect(app.getByText(w.spent, { exact: false })).toHaveCount(0);
        await expect(app.getByText(w.month)).toHaveCount(0);
        await shoot(
          page,
          `ai-run-folded-${locale}-${width}-${theme}`,
          runButton,
        );
        await app.getByRole("button", { name: w.fold }).click();
        await expect(app.getByText(w.spent, { exact: false })).toBeVisible();
        await expect(app.getByText(w.month)).toBeVisible();
        await shoot(
          page,
          `ai-run-ready-${locale}-${width}-${theme}`,
          runButton,
        );

        // Once queued, the server lists the Step as running.
        await setHostReply(page, "list_task_steps", ok(steps("running")));
        await runButton.click();
        await expect(app.getByText(w.queued)).toBeVisible();
        const cancel = app.getByRole("button", { name: w.cancel });
        await expectTappable(cancel);
        await expect(runButton).toHaveCount(0);
        await expect(
          app.locator("li", { hasText: ai.title }).getByRole("img", {
            name:
              locale === "sv"
                ? "Görs av AI, pågår"
                : "Performed by AI, running",
          }),
        ).toBeVisible();
        await shoot(page, `ai-run-queued-${locale}-${width}-${theme}`, cancel);

        // The server finishes: the next background read shows the result to review, with no message to Claude.
        await setHostReply(
          page,
          "get_ai_plan",
          ok(plan("to_review", run("to_review"))),
        );
        await setHostReply(page, "list_task_steps", ok(steps("to_review")));
        await expect(app.getByRole("button", { name: w.review })).toBeVisible({
          timeout: 10_000,
        });
        await expect(app.getByText(w.queued)).toHaveCount(0);
        const calls = (await simulatedHostState(page)).calls;
        expect(
          calls.filter((call) => call.name === "run_ai_plan"),
        ).toHaveLength(1);
        expect(failures).toEqual([]);
      });

for (const locale of ["sv", "en"] as const)
  test(`says a reached cost cap under the Step, calmly (${locale}, 360 px)`, async ({
    page,
  }) => {
    const w = words[locale];
    const { app, failures } = await openTask(page, {
      locale,
      width: 360,
      theme: "light",
      replies: {
        run_ai_plan: {
          structuredContent: { code: "conflict", reason: "ai_budget_reached" },
          isError: true,
        },
      },
    });
    await app.getByRole("button", { name: w.run }).click();
    const note = app.getByText(w.budget);
    await expect(note).toBeVisible();
    await expect(app.getByRole("button", { name: w.run })).toHaveCount(0);
    await expect(app.getByRole("alert")).toHaveCount(0);
    await shoot(page, `ai-run-budget-${locale}-360-light`, note);
    expect(failures).toEqual([]);
  });

test("draws nothing of the server runner when it is off", async ({ page }) => {
  const off = plan("ready", null, false);
  off.plan.server_runner = "off";
  const { app, failures } = await openTask(page, {
    locale: "sv",
    width: 412,
    theme: "light",
    replies: { get_ai_plan: ok(off) },
  });
  await app.getByRole("button", { name: words.sv.fold }).click();
  await expect(app.getByText(/^Budget:/)).toBeVisible();
  await expect(app.getByText(/använt hittills|AI denna månad/)).toHaveCount(0);
  await expect(app.getByRole("button", { name: words.sv.run })).toHaveCount(0);
  expect(failures).toEqual([]);
});
