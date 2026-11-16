import { vi } from "vitest";
import type {
  WorkAiPlan,
  WorkAiPlanStep,
  WorkAiRun,
  WorkStep,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { taskA, transport } from "./work-app-fixtures";

/*
 * Plan, run and Step records for the AI-plan tests. The tests run in jsdom with a simulated host; this is not a real
 * Claude or Android host.
 */

export const DIGEST =
  "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
export const NEW_DIGEST =
  "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210";
export const RUN_ID = "019f0000-0000-7000-8000-0000000000c9";
export const AI_STEP_ID = "019f0000-0000-7000-8000-0000000000b9";
export const OWNER_STEP_ID = "019f0000-0000-7000-8000-0000000000b8";

/** The Task of the plan: taskA marked as possible with AI. */
export const aiTask: WorkTask = { ...taskA, ai_possible: true };

export const ownerStep: WorkStep = {
  id: OWNER_STEP_ID,
  title: "Ring Anna",
  status: "todo",
  due_at: null,
  version: 1,
  performer: "owner",
  ai_status: null,
};

export const aiStep: WorkStep = {
  id: AI_STEP_ID,
  title: "Sök fram priser",
  status: "todo",
  due_at: null,
  version: 1,
  performer: "ai",
  ai_status: "to_review",
};

export function stepRecord(step: WorkStep): WorkAiPlanStep["step"] {
  return {
    archived_at: null,
    attention_requested: false,
    due_at: null,
    id: step.id,
    instruction: null,
    performer: step.performer ?? "owner",
    position: 1,
    status: step.status,
    task_id: taskA.id,
    title: step.title,
    version: step.version,
  };
}

export function runRecord(
  overrides: Partial<WorkAiRun["run"]> = {},
): WorkAiRun["run"] {
  return {
    attempt: 1,
    cost_source: "provider",
    cost_usd: 0.12,
    created_at: "2026-11-16T08:00:00Z",
    failure_category: null,
    finished_at: "2026-11-16T08:01:00Z",
    has_question: false,
    has_result: true,
    id: RUN_ID,
    input_tokens: 100,
    lease_until: null,
    model: "claude-test",
    output_tokens: 50,
    reviewed_at: null,
    runner: "claude_code",
    started_at: "2026-11-16T08:00:10Z",
    state: "to_review",
    step_id: AI_STEP_ID,
    task_id: taskA.id,
    version: 4,
    ...overrides,
  };
}

export function aiPlanStep(
  overrides: Partial<WorkAiPlanStep> = {},
): WorkAiPlanStep {
  return {
    action_titles: [],
    ai_spec: {
      budget: { max_turns: 8, max_usd: 0.5 },
      capabilities: ["web_search", "read_task_context"],
      context: { include_contacts: false, include_references: false },
      done_when: ["three prices are found"],
      effects: "none",
      goal: "Find three prices for the service",
      output: { format: "checklist", max_chars: 4000 },
      privacy: "normal",
      runner: "any",
      spec_version: 1,
      stop_and_ask: ["the budget"],
    },
    ai_status: "to_review",
    attempts: 1,
    latest_run: null,
    server_startable: false,
    step: stepRecord(aiStep),
    ...overrides,
  };
}

export function ownerPlanStep(): WorkAiPlanStep {
  return {
    action_titles: [],
    ai_spec: null,
    ai_status: null,
    attempts: 0,
    latest_run: null,
    server_startable: false,
    step: stepRecord(ownerStep),
  };
}

export function plan(overrides: Partial<WorkAiPlan> = {}): WorkAiPlan {
  return {
    ai_possible: true,
    approved_at: null,
    digest: DIGEST,
    month_cap_usd: 0,
    month_spent_usd: 0,
    server_runner: "off",
    state: "draft",
    steps: [ownerPlanStep(), aiPlanStep()],
    task_cap_usd: 2,
    task_id: taskA.id,
    task_spent_usd: 0,
    task_title: taskA.title,
    task_version: taskA.version,
    ...overrides,
  };
}

export function noPlan(): WorkAiPlan {
  return plan({ state: "none", steps: [], digest: "" });
}

/** A run with content, as get_ai_step_run (include_content) returns it. */
export function run(
  runOverrides: Partial<WorkAiRun["run"]> = {},
  content: Partial<NonNullable<WorkAiRun["content"]>> = {},
): WorkAiRun {
  return {
    run: runRecord(runOverrides),
    content: {
      answer: null,
      checklist: [],
      comment: null,
      note: "",
      question: null,
      result_format: "text",
      result_summary: null,
      result_text: "Three prices: 100, 120, 140.",
      ...content,
    },
  };
}

/** A transport for a Task marked as possible with AI whose plan holds one owner Step and one AI Step. */
export function aiTransport(
  overrides: Partial<WorkTransport> = {},
  steps: WorkStep[] = [ownerStep, aiStep],
): WorkTransport {
  return transport({
    getTask: vi.fn().mockResolvedValue({ task: aiTask }),
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: steps, next_cursor: null }),
    getAiPlan: vi.fn().mockResolvedValue({ plan: plan() }),
    ...overrides,
  });
}

/** An approved plan whose AI Step's latest run waits for the owner (a result to review or a question to answer). */
export function reviewPlan(
  state: "to_review" | "needs_input" = "to_review",
): WorkAiPlan {
  const latest = runRecord({
    state,
    has_result: state === "to_review",
    has_question: state === "needs_input",
  });
  return plan({
    state: "approved",
    approved_at: "2026-11-16T08:00:00Z",
    steps: [
      ownerPlanStep(),
      aiPlanStep({ ai_status: state, latest_run: latest }),
    ],
  });
}

/**
 * An approved plan on a server that runs AI Steps. `step` sets the AI Step: by default it is ready and the server may
 * run it; `serverRun` gives it a run the server holds (queued or running).
 */
export function serverPlan(
  overrides: Partial<WorkAiPlan> = {},
  step: Partial<WorkAiPlanStep> = {},
): WorkAiPlan {
  return plan({
    state: "approved",
    approved_at: "2026-11-16T08:00:00Z",
    server_runner: "available",
    month_cap_usd: 50,
    steps: [
      ownerPlanStep(),
      aiPlanStep({
        ai_status: "ready",
        attempts: 0,
        server_startable: true,
        ...step,
      }),
    ],
    ...overrides,
  });
}

/** The AI Step's run as the server holds it: queued or under way, not yet finished. */
export function serverRun(
  state: "queued" | "running",
  overrides: Partial<WorkAiRun["run"]> = {},
): WorkAiRun["run"] {
  return runRecord({
    runner: "server",
    state,
    has_result: false,
    finished_at: null,
    started_at: state === "running" ? "2026-11-16T08:00:10Z" : null,
    cost_usd: 0,
    version: 1,
    ...overrides,
  });
}
