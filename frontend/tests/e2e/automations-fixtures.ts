/**
 * Automations in the shape the server's tools answer (list_automations, get_automation, approve_automation,
 * get_automation_report), for the simulated host and the room tests. Synthetic data only; a digest here is a run of
 * one hex digit, never a real one.
 */
import type { ToolResults } from "../../src/lib/mcp/tool-results.generated";

type Automation = ToolResults["get_automation"]["automation"];
type Summary = ToolResults["list_automations"]["items"][number];
type Report = ToolResults["get_automation_report"];

export const aid = (n: number) =>
  `019f1000-0000-7000-8000-${String(n).padStart(12, "0")}`;
const digest = (digit: string) => digit.repeat(64);

function automation(n: number, partial: Partial<Automation>): Automation {
  return {
    allowed_effects: ["create_task"],
    apply_mode: "suggest",
    approval: "not_approved",
    approved_at: null,
    auto_apply_confirmed: false,
    auto_apply_limits: { per_run: 10, per_day: 25 },
    auto_effects: [],
    auto_threshold: 95,
    bulk_threshold: 90,
    cadence: {
      frequency: "daily",
      interval: 1,
      weekdays: [],
      day_of_month: null,
      last_weekday: false,
      until: null,
      local_time: "07:00",
    },
    changed_since_approval: false,
    created_at: "2026-11-20T08:00:00Z",
    id: aid(n),
    instruction: "Läs nya mejl sedan förra körningen och föreslå uppgifter.",
    last_run_at: null,
    max_suggestions_per_run: 15,
    model_tier: "standard",
    pending_suggestions: 0,
    purpose: "Föreslår uppgifter ur morgonens mejl.",
    run_budget_usd: 1,
    runnable: false,
    runner: "server",
    sources: ["mail"],
    spec_digest: digest(String(n % 10)),
    state: "draft",
    title: "Utan titel",
    updated_at: "2026-11-22T08:00:00Z",
    version: 1,
    ...partial,
  };
}

/** Approved and running: suggestions wait for the owner one by one. */
export const morning = automation(1, {
  title: "Morgonmejl",
  purpose:
    "Läser mejlen som kommit sedan i går och föreslår uppgifter och nya kontakter.",
  instruction:
    "Läs mejl som kommit sedan förra körningen.\nFöreslå en uppgift för varje fråga som väntar på svar från mig, med förfallodag om mejlet nämner en.\nFöreslå en kontakt för en ny avsändare som skriver om ett pågående projekt.\nHoppa över nyhetsbrev och kvitton.",
  sources: ["calendar", "mail"],
  allowed_effects: ["create_contact", "create_task"],
  cadence: {
    frequency: "weekly",
    interval: 1,
    weekdays: [0, 1, 2, 3, 4],
    day_of_month: null,
    last_weekday: false,
    until: null,
    local_time: "07:00",
  },
  approval: "approved",
  approved_at: "2026-11-20T09:12:00Z",
  state: "active",
  runnable: true,
  last_run_at: "2026-11-23T06:02:00Z",
  pending_suggestions: 3,
  version: 4,
});

/** A draft that applies tasks without a click: its approval needs the separate confirmation. */
export const invoices = automation(2, {
  title: "Fakturakoll",
  purpose:
    "Lägger upp en uppgift att betala för varje ny faktura som kommer med mejlet.",
  instruction:
    "Leta efter fakturor i nya mejl. Skapa en uppgift ”Betala faktura från …” med förfallodagen på fakturan. Föreslå aldrig något om betalningen redan är gjord.",
  apply_mode: "auto_low_risk",
  auto_effects: ["create_task"],
  auto_threshold: 95,
  max_suggestions_per_run: 10,
  run_budget_usd: 0.5,
  runner: "server",
  version: 2,
});

/** Changed after its approval: it does not run until it is approved again. */
export const evening = automation(3, {
  title: "Kvällsgenomgång",
  purpose: "Sammanfattar dagens möten och föreslår uppföljningar.",
  instruction:
    "Gå igenom dagens kalender och föreslå en uppföljning per möte som saknar en.",
  sources: ["calendar", "sidekick"],
  cadence: {
    frequency: "daily",
    interval: 1,
    weekdays: [],
    day_of_month: null,
    last_weekday: false,
    until: null,
    local_time: "18:30",
  },
  approval: "changed_since_approval",
  changed_since_approval: true,
  approved_at: "2026-11-18T19:00:00Z",
  last_run_at: "2026-11-21T17:30:00Z",
  runner: "claude",
  model_tier: "strong",
  version: 6,
});

/** Paused by the owner, approved. */
export const weekly = automation(4, {
  title: "Veckorapport",
  purpose: "Föreslår veckans tre viktigaste uppgifter varje måndag.",
  cadence: null,
  sources: ["sidekick"],
  approval: "approved",
  approved_at: "2026-11-10T08:00:00Z",
  state: "paused",
  last_run_at: "2026-11-17T07:00:00Z",
  runner: "claude_code",
});

const summary = (record: Automation): Summary => ({
  approval: record.approval,
  auto_apply_confirmed: record.auto_apply_confirmed,
  changed_since_approval: record.changed_since_approval,
  id: record.id,
  last_run_at: record.last_run_at,
  model_tier: record.model_tier,
  pending_suggestions: record.pending_suggestions,
  runnable: record.runnable,
  runner: record.runner,
  state: record.state,
  title: record.title,
  version: record.version,
});

export const records = [morning, invoices, evening, weekly];

export const automationsPage: ToolResults["list_automations"] = {
  items: records.map(summary),
  next_cursor: null,
};

export const emptyAutomations: ToolResults["list_automations"] = {
  items: [],
  next_cursor: null,
};

const counts = (partial: Partial<Report["totals"]>): Report["totals"] => ({
  applied: 0,
  auto_applied: 0,
  cost_usd: 0,
  dismissed: 0,
  failed_runs: 0,
  flagged: 0,
  ok_runs: 0,
  pending: 0,
  runs: 0,
  suggestions_created: 0,
  ...partial,
});

export const report: Report = {
  automations: [
    {
      automation_id: morning.id,
      counts: counts({
        runs: 3,
        ok_runs: 2,
        failed_runs: 1,
        suggestions_created: 7,
        applied: 4,
        pending: 3,
        cost_usd: 0.09,
      }),
      model_tier: "standard",
      state: "active",
      title: morning.title,
    },
  ],
  highlights: [
    {
      ai_summary: null,
      at: "2026-11-22T06:01:00Z",
      automation_id: morning.id,
      automation_title: morning.title,
      effect: null,
      flags: null,
      kind: "run_failed",
      outcome: "budget",
      run_id: aid(901),
      suggestion_id: null,
      verdict: null,
    },
  ],
  omitted_automations: 0,
  report_version: 3,
  totals: counts({ runs: 3, failed_runs: 1, suggestions_created: 7 }),
  window: {
    basis: "last_seen",
    since: "2026-11-20T18:00:00Z",
    until: "2026-11-23T08:00:00Z",
  },
};

/** The record the server answers after an approval: approved at the same digest, a draft made active. */
export function approvedOf(record: Automation): Automation {
  return {
    ...record,
    approval: "approved",
    changed_since_approval: false,
    approved_at: "2026-11-23T08:00:00Z",
    state: record.state === "draft" ? "active" : record.state,
    runnable: record.state !== "paused",
    version: record.version + 1,
  };
}

const reply = (structuredContent: unknown) => ({ structuredContent });

/** The host's answers: the list, each automation by id, the report, and approvals that succeed. */
export const automationReplies = {
  list_automations: reply(automationsPage),
  get_automation: {
    __byArgument: {
      key: "automation_id",
      answers: Object.fromEntries(
        records.map((record) => [record.id, reply({ automation: record })]),
      ),
    },
  },
  get_automation_report: reply(report),
  approve_automation: {
    __byArgument: {
      key: "automation_id",
      answers: Object.fromEntries(
        records.map((record) => [
          record.id,
          reply({ automation: approvedOf(record) }),
        ]),
      ),
    },
  },
};
