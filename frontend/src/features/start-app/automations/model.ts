/**
 * The automations as pure functions: what list_automations, get_automation and get_automation_report answer, put
 * into the owner's words, and what an approval sends. Nothing here decides whether an automation may run or what it
 * may apply: the server binds the approval to the spec's digest and refuses one that does not match. The app sends
 * the digest exactly as it was shown, and the confirmation that lets suggestions apply without a click only after the
 * owner gave it in its own step.
 *
 * An automation's title, purpose and instruction are the owner's own (drafted with Claude); they are shown as plain
 * text. The report's `ai_summary` is AI-written and is not shown.
 */
import type { ToolResults } from "@/lib/mcp/tool-results.generated";
import { ownerDateFormat } from "../../mcp-apps/app-timezone";
import { everyEn, everySv, type RuleWords } from "../../mcp-apps/repeat-words";
import type { AutomationLabels } from "./labels";

export type AutomationPage = ToolResults["list_automations"];
export type AutomationSummary = AutomationPage["items"][number];
export type AutomationRecord = ToolResults["get_automation"]["automation"];
export type AutomationReport = ToolResults["get_automation_report"];
export type ReportHighlight = AutomationReport["highlights"][number];
export type ReportCounts = AutomationReport["totals"];

/** approve_automation's arguments, as the app sends them. */
export type ApproveArguments = {
  automation_id: string;
  spec_digest: string;
  idempotency_key: string;
  auto_apply_confirmed?: true;
};

/**
 * The server's caps on what one automation applies without a click (automations/domain/grouping.py,
 * MAX_AUTO_PER_RUN and MAX_AUTO_PER_DAY). The record carries them (`auto_apply_limits`); these are the fallback for
 * an answer that lacks them. The confirmation names them, so they must follow the server's.
 */
export const MAX_AUTO_PER_RUN = 10;
export const MAX_AUTO_PER_DAY = 25;

/** The caps the confirmation names: the record's own, or the constants when the answer carries none. */
export function autoApplyLimits(record: {
  auto_apply_limits?: { per_run?: number; per_day?: number };
}): { perRun: number; perDay: number } {
  return {
    perRun: record.auto_apply_limits?.per_run ?? MAX_AUTO_PER_RUN,
    perDay: record.auto_apply_limits?.per_day ?? MAX_AUTO_PER_DAY,
  };
}

/** The highlights of one automation the detail shows. */
export const DETAIL_HIGHLIGHTS = 3;

type Obj = Record<string, unknown>;
const isObj = (value: unknown): value is Obj =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** A list_automations answer. */
export function isAutomationPage(value: unknown): value is AutomationPage {
  return (
    isObj(value) &&
    Array.isArray(value.items) &&
    value.items.every(
      (item) =>
        isObj(item) &&
        typeof item.id === "string" &&
        typeof item.approval === "string",
    )
  );
}

/** A get_automation (or approve_automation) answer with the whole record; an id-only root is not one. */
export function isAutomationResult(
  value: unknown,
): value is ToolResults["get_automation"] {
  return (
    isObj(value) &&
    isObj(value.automation) &&
    typeof value.automation.id === "string" &&
    typeof value.automation.spec_digest === "string"
  );
}

/** The id of the automation a result names, whole or id-only (`{ automation: { id } }`). */
export function automationIdOf(value: unknown): string | undefined {
  if (!isObj(value) || !isObj(value.automation)) return undefined;
  const id = value.automation.id;
  return typeof id === "string" && id !== "" ? id : undefined;
}

export type StateKey = keyof AutomationLabels["states"];

/** Where an automation stands, as one of the five words its row and detail use. */
export function stateOf(
  item: Pick<AutomationSummary, "state" | "approval">,
): StateKey {
  if (item.state === "archived") return "archived";
  if (item.approval === "changed_since_approval") return "changed";
  if (item.approval === "not_approved") return "waiting";
  return item.state === "paused" ? "paused" : "on";
}

/** Whether the owner's approval is what the automation waits for. */
export function waitsForApproval(
  item: Pick<AutomationSummary, "state" | "approval">,
): boolean {
  const state = stateOf(item);
  return state === "waiting" || state === "changed";
}

/** A moment in the owner's zone: "ons 18 nov 07:02" (or the day alone). */
export function momentText(
  at: string,
  locale: string,
  withTime = true,
): string {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return at;
  // The day and the time are formatted apart, so the day reads as every other day in the apps ("mån 23 nov").
  const day = ownerDateFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(when);
  if (!withTime) return day;
  const time = ownerDateFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(when);
  return `${day} ${time}`;
}

/** The row's line under the title: its state, what waits, and when it last ran. */
export function rowMeta(item: AutomationSummary, t: AutomationLabels): string {
  const state = stateOf(item);
  const parts = [t.states[state]];
  if (item.pending_suggestions > 0)
    parts.push(t.pending(item.pending_suggestions));
  if ((state === "on" || state === "paused") && item.last_run_at)
    parts.push(t.lastRun(momentText(item.last_run_at, t.dateLocale, false)));
  return parts.join(" · ");
}

/** The list: the ones that wait for the owner first, then the others in the server's order. */
export function listOrder(items: readonly AutomationSummary[]) {
  return [
    ...items.filter((item) => waitsForApproval(item)),
    ...items.filter((item) => !waitsForApproval(item)),
  ];
}

/** "a", "a och b", "a, b och c". */
function listWords(names: readonly string[], and: string): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} ${and} ${names[names.length - 1]}`;
}

/** The text with its first letter in upper case: a value that starts a line ("Nya uppgifter"). */
export const capital = (text: string) =>
  text === "" ? text : `${text[0]?.toUpperCase() ?? ""}${text.slice(1)}`;

const FREQUENCIES = new Set(["daily", "weekly", "monthly", "yearly"]);

/** When it runs: "Varje dag kl. 07:00", "Varje mån och tors kl. 07:00", or "Bara när du startar den". */
export function scheduleText(
  cadence: AutomationRecord["cadence"],
  t: AutomationLabels,
): string {
  if (!cadence) return t.manualOnly;
  if (!FREQUENCIES.has(cadence.frequency)) return cadence.local_time;
  const rule = {
    ...cadence,
    frequency: cadence.frequency as RuleWords["frequency"],
  };
  const every = t.dateLocale.startsWith("en") ? everyEn(rule) : everySv(rule);
  return t.at(capital(every), cadence.local_time);
}

/** What it reads: "Mejl och Kalender". */
export function sourcesText(
  sources: AutomationRecord["sources"],
  t: AutomationLabels,
): string {
  if (sources.length === 0) return t.nothing;
  return listWords(
    sources.map((source) => t.sources[source]),
    t.and,
  );
}

/** What it may create, in a sentence: "nya uppgifter och nya kontakter" (lower case; `capital` for a value). */
export function effectsWords(
  effects: AutomationRecord["allowed_effects"],
  t: AutomationLabels,
): string {
  return listWords(
    effects.map((effect) => t.effects[effect]),
    t.and,
  );
}

/** The facts of one automation, in the order the detail lists them: a label, a value and an optional muted note. */
export type Fact = { key: string; label: string; value: string; note?: string };

export function factsOf(record: AutomationRecord, t: AutomationLabels): Fact[] {
  const effects =
    record.allowed_effects.length > 0
      ? capital(effectsWords(record.allowed_effects, t))
      : t.nothing;
  const auto = record.apply_mode === "auto_low_risk";
  const handling: Fact = auto
    ? {
        key: "handling",
        label: t.facts.handling,
        value:
          record.auto_effects.length > 0
            ? t.appliesDirectly(
                effectsWords(record.auto_effects, t),
                record.auto_threshold,
              )
            : t.appliesNothingYet,
        note: t.restWait,
      }
    : {
        key: "handling",
        label: t.facts.handling,
        value: t.decideEach,
        note: t.groupedFrom(record.bulk_threshold),
      };
  return [
    {
      key: "schedule",
      label: t.facts.schedule,
      value: scheduleText(record.cadence, t),
    },
    {
      key: "sources",
      label: t.facts.sources,
      value: sourcesText(record.sources, t),
    },
    { key: "effects", label: t.facts.effects, value: effects },
    handling,
    {
      key: "limits",
      label: t.facts.limits,
      value: t.limits(
        record.max_suggestions_per_run,
        t.usd(record.run_budget_usd),
      ),
    },
    {
      key: "runner",
      label: t.facts.runner,
      value: t.runners[record.runner],
    },
    {
      key: "model",
      label: t.facts.model,
      value: t.models[record.model_tier],
    },
  ];
}

/** What the approval asks of the owner now. */
export type ApprovalNeed =
  | { kind: "approved"; auto: boolean; paused: boolean; at: string | null }
  | { kind: "archived" }
  | { kind: "incomplete"; missing: ("sources" | "effects")[] }
  | { kind: "approve"; auto: boolean; changed: boolean };

/**
 * The approval's state, from the record as the server answered it. A spec without sources or effects is refused by
 * the server, so it is not offered; an archived one must be restored first. `auto`: the spec applies suggestions
 * without a click, so its approval needs the separate confirmation.
 */
export function approvalNeed(record: AutomationRecord): ApprovalNeed {
  const auto = record.apply_mode === "auto_low_risk";
  if (record.state === "archived") return { kind: "archived" };
  if (record.approval === "approved")
    return {
      kind: "approved",
      auto,
      paused: record.state === "paused",
      at: record.approved_at,
    };
  const missing: ("sources" | "effects")[] = [];
  if (record.sources.length === 0) missing.push("sources");
  if (record.allowed_effects.length === 0) missing.push("effects");
  if (missing.length > 0) return { kind: "incomplete", missing };
  return {
    kind: "approve",
    auto,
    changed: record.approval === "changed_since_approval",
  };
}

/**
 * approve_automation's arguments for the record as it was shown: its id and its digest, unchanged. A spec that
 * applies without a click is sent only with the owner's confirmation, and then with `auto_apply_confirmed: true`;
 * without it there is nothing to send (undefined). A spec that only proposes never carries the confirmation.
 */
export function approveArguments(
  record: Pick<AutomationRecord, "id" | "spec_digest" | "apply_mode">,
  confirmed: boolean,
  idempotencyKey: string,
): ApproveArguments | undefined {
  const auto = record.apply_mode === "auto_low_risk";
  if (auto && !confirmed) return undefined;
  return {
    automation_id: record.id,
    spec_digest: record.spec_digest,
    idempotency_key: idempotencyKey,
    ...(auto ? { auto_apply_confirmed: true as const } : {}),
  };
}

/** The report's row of one automation, and its highlights (at most DETAIL_HIGHLIGHTS, newest first as served). */
export function reportOf(
  report: AutomationReport,
  id: string,
): { counts?: ReportCounts; highlights: ReportHighlight[] } {
  return {
    counts: report.automations.find((row) => row.automation_id === id)?.counts,
    highlights: report.highlights
      .filter((item) => item.automation_id === id)
      .slice(0, DETAIL_HIGHLIGHTS),
  };
}

/** "4 körningar · 1 misslyckades · 6 förslag · 2 väntar · 0,12 USD". */
export function countsLine(counts: ReportCounts, t: AutomationLabels): string {
  const parts = [t.runs(counts.runs)];
  if (counts.failed_runs > 0) parts.push(t.failed(counts.failed_runs));
  parts.push(t.made(counts.suggestions_created));
  if (counts.pending > 0) parts.push(t.waitingNow(counts.pending));
  if (counts.auto_applied > 0) parts.push(t.autoApplied(counts.auto_applied));
  parts.push(t.usd(counts.cost_usd));
  return parts.join(" · ");
}

/** One highlight in words: "Körningen misslyckades: budgeten tog slut". */
export function highlightText(
  item: ReportHighlight,
  t: AutomationLabels,
): string {
  const what = t.highlights[item.kind] ?? item.kind;
  if (item.kind === "run_failed" && item.outcome && item.outcome !== "failed")
    return `${what}: ${t.outcomes[item.outcome]}`;
  return what;
}
