import type { WorkAiPlan, WorkAiPlanStep } from "../transport/transport";

type AiSpec = NonNullable<WorkAiPlanStep["ai_spec"]>;
type Capability = AiSpec["capabilities"][number];
type OutputFormat = AiSpec["output"]["format"];

/** "a, b och c" / "a, b and c": a short list in running text. */
function listOf(items: readonly string[], and: string): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} ${and} ${items.at(-1)}`;
}

/**
 * Words of a Task's AI steps: the mark in the ⋯ menu and on the row, the plan card, the Step's AI line and the review of
 * a run's result. Swedish comes first and is the default; the English key set must stay identical to it
 * (tests/features/work-app/ai/ai-plan.test.tsx checks that).
 */
export const aiLabelsSv = {
  /** The ⋯ entry (pressed while the Task is marked) and the row's mark read aloud. */
  possible: "Möjlig med AI",
  /** The short mark on a Task's row. */
  mark: "AI",
  heading: "AI-plan",
  loading: "Läser AI-planen …",
  none: "Ingen plan än.",
  askPlan: "Be Claude planera",
  askPlanMessage: (title: string, id: string) =>
    `Planera uppgiften "${title}" med AI-steg. Uppgiftens id är ${id}.`,
  change: "Ändra",
  changeMessage: (title: string, id: string) =>
    `Jag vill ändra AI-planen för uppgiften "${title}" (id ${id}).`,
  approve: "Godkänn plan",
  draft: "Väntar på ditt godkännande",
  approvedAt: (when: string) => `Godkänd ${when}`,
  changed: "Planen har ändrats – godkänn igen",
  approvedNow: "Planen är godkänd.",
  approveFailed: "Godkännandet sparades inte.",
  approveConflict: "Planen har ändrats sedan du läste den.",
  approveForbidden: "Du har inte behörighet att godkänna planen.",
  showSteps: (count: number) => `Visa stegen (${count})`,
  hideSteps: "Dölj stegen",
  detailsFor: (title: string) => `Vad AI-steget ${title} ska göra`,
  doneWhen: (items: readonly string[]) => `Klart när ${listOf(items, "och")}.`,
  tools: (items: readonly string[]) =>
    items.length ? `Får använda ${listOf(items, "och")}.` : "Inga verktyg.",
  capability: {
    web_search: "webbsökning",
    web_fetch: "webbsidor",
    read_task_context: "uppgiftens text",
    code: "kod",
  } satisfies Record<Capability, string>,
  output: (format: OutputFormat, chars: string) =>
    `Lämnar ${FORMAT_SV[format]}, högst ${chars} tecken.`,
  asks: (items: readonly string[]) => `Frågar dig om ${listOf(items, "och")}.`,
  stepBudget: (usd: string) => `Högst ${usd} per försök.`,
  budget: (steps: string, cap: string) =>
    `Budget: ${steps} för AI-stegen, tak ${cap} för uppgiften.`,
  /** The opener under an AI Step that has a run to look at, by what the run waits for. */
  openRun: {
    review: "Granska resultatet",
    question: "Svara på frågan",
    look: "Visa körningen",
  },
  resultFor: (title: string) => `Resultat för ${title}`,
  loadingRun: "Läser resultatet …",
  attempt: (n: number) => `försök ${n}`,
  estimated: "uppskattat",
  question: "AI-steget frågar:",
  checklist: (done: number, total: number) =>
    `Rapporterat klart: ${done} av ${total} ${total === 1 ? "åtgärd" : "åtgärder"}.`,
  failed: (category: string | null) =>
    category
      ? `Körningen misslyckades (${category}).`
      : "Körningen misslyckades.",
  yourComment: "Din kommentar:",
  yourAnswer: "Ditt svar:",
  showAll: "Visa hela",
  showLess: "Visa mindre",
  accept: "Godkänn resultat",
  redo: "Gör om",
  redoComment: "Kommentar till nästa försök",
  sendRedo: "Gör om med kommentar",
  reject: "Avvisa",
  answer: "Svara",
  answerLabel: "Ditt svar",
  cancel: "Avbryt",
  reviewed: {
    accept: "Godkänt.",
    redo: "Skickat för ett nytt försök.",
    reject: "Avvisat.",
    answer: "Svaret är skickat.",
  },
  reviewFailed: "Det gick inte att spara.",
  reviewConflict: "Körningen har ändrats sedan du läste den.",
  reload: "Läs in igen",
};
export type AiLabels = typeof aiLabelsSv;

const FORMAT_SV: Record<OutputFormat, string> = {
  text: "text",
  markdown: "formaterad text",
  checklist: "en checklista",
  table: "en tabell",
  email_draft: "ett e-postutkast",
};
const FORMAT_EN: Record<OutputFormat, string> = {
  text: "text",
  markdown: "formatted text",
  checklist: "a checklist",
  table: "a table",
  email_draft: "an email draft",
};

export const aiLabelsEn: AiLabels = {
  possible: "Possible with AI",
  mark: "AI",
  heading: "AI plan",
  loading: "Reading the AI plan …",
  none: "No plan yet.",
  askPlan: "Ask Claude to plan",
  askPlanMessage: (title, id) =>
    `Plan the task "${title}" with AI steps. The task's id is ${id}.`,
  change: "Change",
  changeMessage: (title, id) =>
    `I want to change the AI plan for the task "${title}" (id ${id}).`,
  approve: "Approve plan",
  draft: "Waiting for your approval",
  approvedAt: (when) => `Approved ${when}`,
  changed: "The plan has changed – approve it again",
  approvedNow: "The plan is approved.",
  approveFailed: "The approval was not saved.",
  approveConflict: "The plan has changed since you read it.",
  approveForbidden: "You don’t have permission to approve the plan.",
  showSteps: (count) => `Show the steps (${count})`,
  hideSteps: "Hide the steps",
  detailsFor: (title) => `What the AI step ${title} will do`,
  doneWhen: (items) => `Done when ${listOf(items, "and")}.`,
  tools: (items) =>
    items.length ? `May use ${listOf(items, "and")}.` : "No tools.",
  capability: {
    web_search: "web search",
    web_fetch: "web pages",
    read_task_context: "the task’s text",
    code: "code",
  },
  output: (format, chars) =>
    `Returns ${FORMAT_EN[format]}, at most ${chars} characters.`,
  asks: (items) => `Asks you about ${listOf(items, "and")}.`,
  stepBudget: (usd) => `At most ${usd} per attempt.`,
  budget: (steps, cap) =>
    `Budget: ${steps} for the AI steps, a cap of ${cap} for the task.`,
  openRun: {
    review: "Review the result",
    question: "Answer the question",
    look: "Show the run",
  },
  resultFor: (title) => `Result for ${title}`,
  loadingRun: "Reading the result …",
  attempt: (n) => `attempt ${n}`,
  estimated: "estimated",
  question: "The AI step asks:",
  checklist: (done, total) =>
    `Reported done: ${done} of ${total} ${total === 1 ? "action" : "actions"}.`,
  failed: (category) =>
    category ? `The run failed (${category}).` : "The run failed.",
  yourComment: "Your comment:",
  yourAnswer: "Your answer:",
  showAll: "Show all",
  showLess: "Show less",
  accept: "Accept result",
  redo: "Redo",
  redoComment: "Comment for the next attempt",
  sendRedo: "Redo with comment",
  reject: "Reject",
  answer: "Answer",
  answerLabel: "Your answer",
  cancel: "Cancel",
  reviewed: {
    accept: "Accepted.",
    redo: "Sent back for another attempt.",
    reject: "Rejected.",
    answer: "Answer sent.",
  },
  reviewFailed: "Could not save.",
  reviewConflict: "The run has changed since you read it.",
  reload: "Reload",
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function aiLabelsFor(dateLocale: string): AiLabels {
  return dateLocale.toLowerCase().startsWith("sv") ? aiLabelsSv : aiLabelsEn;
}

/** An amount in US dollars with two decimals in the locale's digits: "0,50 USD" / "0.50 USD". */
export function usd(amount: number, dateLocale: string): string {
  return `${amount.toLocaleString(dateLocale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} USD`;
}

/** When the plan was approved: the time today, else the day and the time ("3 nov. 14:02"). */
export function approvedWhen(
  approvedAt: string,
  dateLocale: string,
  now = new Date(),
): string {
  const at = new Date(approvedAt);
  const time = at.toLocaleTimeString(dateLocale, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (at.toDateString() === now.toDateString()) return time;
  const day = at.toLocaleDateString(dateLocale, {
    day: "numeric",
    month: "short",
  });
  return `${day} ${time}`;
}

/** True while the owner's click is what the plan waits for: a draft, or a plan changed after its approval. */
export function needsApproval(plan: WorkAiPlan): boolean {
  return plan.state === "draft" || plan.state === "changed_since_approval";
}
