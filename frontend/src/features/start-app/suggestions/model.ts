/**
 * The suggestion inbox as pure functions: what the tools answer, sorted into the server's safe groups and the cards to
 * review one by one, and every word a card shows taken from closed codes or from the payload's own fields. Nothing
 * here decides who may approve what: which cards are safe together is the server's `groups` (bulk eligibility), and
 * the check's trust is read from the server's codes by `decisionTrust`.
 *
 * Text a suggestion carries (its summary, its rationale, the payload's values, a source's fields) was written by an
 * automation from untrusted sources. It is shown as plain text only, and never reaches a trust note.
 */
import type { ToolResults } from "@/lib/mcp/tool-results.generated";
import { ownerDateFormat } from "../../mcp-apps/app-timezone";
import type { RoomTarget } from "../../mcp-apps/room-types";
import {
  decisionTrust,
  type SuggestionCheck,
} from "../../mcp-apps/ui/decision-codes";
import type {
  DecisionChange,
  DecisionTrust,
} from "../../mcp-apps/ui/decision-card";
import type { SuggestionLabels } from "./labels";

export type SuggestionPage = ToolResults["list_suggestions"];
export type SuggestionItem = SuggestionPage["items"][number];
export type SuggestionGroup = SuggestionPage["groups"][number];
export type SuggestionDetail = ToolResults["get_suggestion"]["suggestion"];
export type DecisionsResult = ToolResults["decide_suggestions"];
export type DecisionOutcome = DecisionsResult["items"][number];
export type UndoResult = ToolResults["undo_suggestion"];

/** At most this many suggestions per confirmation, in the app as in Claude's voice mode. */
export const MAX_PER_CONFIRMATION = 3;

type Obj = Record<string, unknown>;
const isObj = (value: unknown): value is Obj =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** A list_suggestions answer. */
export function isSuggestionPage(value: unknown): value is SuggestionPage {
  return (
    isObj(value) &&
    Array.isArray(value.items) &&
    Array.isArray(value.groups) &&
    typeof value.hidden === "number"
  );
}

/** A get_suggestion answer with the whole card (an id-only root `{ suggestion: { id } }` is not one). */
export function isSuggestionDetail(
  value: unknown,
): value is ToolResults["get_suggestion"] {
  return (
    isObj(value) &&
    isObj(value.suggestion) &&
    typeof value.suggestion.id === "string" &&
    typeof value.suggestion.summary === "string"
  );
}

/** The id of the suggestion a result names, whole or id-only. */
export function suggestionIdOf(value: unknown): string | undefined {
  if (!isObj(value) || !isObj(value.suggestion)) return undefined;
  const id = value.suggestion.id;
  return typeof id === "string" && id !== "" ? id : undefined;
}

/** A decide_suggestions or approve_suggestion_group answer. */
export function isDecisions(value: unknown): value is DecisionsResult {
  return (
    isObj(value) &&
    Array.isArray(value.items) &&
    value.items.every(
      (item) =>
        isObj(item) &&
        typeof item.suggestion_id === "string" &&
        typeof item.state === "string",
    )
  );
}

/** An undo_suggestion answer. */
export function isUndo(value: unknown): value is UndoResult {
  return (
    isObj(value) &&
    typeof value.suggestion_id === "string" &&
    "trashed" in value
  );
}

/**
 * The card's title in the app's language: the effect's own words and the payload's value ("Skapa uppgift: Ring
 * Karin"). The server's line is "Create task: …" in English; only its value is kept, so no other text can take the
 * effect's place. A line without the known prefix is shown as it is.
 */
export function suggestionTitle(
  effect: SuggestionItem["effect"],
  summary: string,
  t: SuggestionLabels,
): string {
  const prefix = SERVER_PREFIX[effect];
  const words = t.effects[effect];
  if (summary === prefix) return words;
  if (summary.startsWith(`${prefix}: `))
    return `${words}: ${summary.slice(prefix.length + 2)}`;
  return summary;
}

/** The payload's value alone ("Ring Karin"), for a receipt. */
export function suggestionValue(
  effect: SuggestionItem["effect"],
  summary: string,
): string {
  const prefix = `${SERVER_PREFIX[effect]}: `;
  return summary.startsWith(prefix) ? summary.slice(prefix.length) : summary;
}

const SERVER_PREFIX: Record<SuggestionItem["effect"], string> = {
  create_task: "Create task",
  create_contact: "Create contact",
};

/**
 * The card's trust from what the server keeps: the check's state, verdict and confidence, the screen's flags, and
 * the latest check's reason codes (only the detail has them).
 */
export function suggestionTrust(
  card: Pick<SuggestionItem, "check" | "flags">,
  locale: string,
  reasonCodes: readonly string[] = [],
): DecisionTrust {
  const check: SuggestionCheck = {
    check_state: card.check.state,
    verdict: card.check.verdict,
    confidence: card.check.confidence,
    screening_flags: card.flags,
    reason_codes: reasonCodes,
  };
  return decisionTrust(check, locale);
}

/** The reason codes of the latest check (the highest attempt). */
export function latestReasons(detail: SuggestionDetail): string[] {
  const latest = [...detail.checks].sort((a, b) => b.attempt - a.attempt)[0];
  return latest ? [...latest.reason_codes] : [];
}

/** One safe group with the cards of this page it holds, in the page's order. */
export type InboxGroup = { group: SuggestionGroup; items: SuggestionItem[] };

/**
 * The page sorted for the inbox: the server's safe groups first, each with its cards, then every other pending card
 * to review alone. A card is in a group only when the server listed it there; the app adds none.
 */
export function inboxOf(page: SuggestionPage): {
  groups: InboxGroup[];
  review: SuggestionItem[];
} {
  const byId = new Map(page.items.map((item) => [item.id, item]));
  const grouped = new Set<string>();
  const groups: InboxGroup[] = [];
  for (const group of page.groups) {
    const items = group.suggestion_ids
      .map((id) => byId.get(id))
      .filter((item): item is SuggestionItem => item !== undefined);
    if (items.length === 0) continue;
    for (const item of items) grouped.add(item.id);
    groups.push({ group, items });
  }
  const review = page.items.filter(
    (item) => !grouped.has(item.id) && item.state === "pending",
  );
  return { groups, review };
}

/** How many cards wait in the page: the groups' and the single ones. */
export function waitingCount(page: SuggestionPage): number {
  const { groups, review } = inboxOf(page);
  return groups.reduce((sum, { items }) => sum + items.length, review.length);
}

/** A page with the next page's cards and groups after its own, the next page's cursor and hidden count. */
export function appendPage(
  page: SuggestionPage,
  next: SuggestionPage,
): SuggestionPage {
  const seen = new Set(page.items.map((item) => item.id));
  const digests = new Set(page.groups.map((group) => group.group_digest));
  return {
    items: [...page.items, ...next.items.filter((item) => !seen.has(item.id))],
    groups: [
      ...page.groups,
      ...next.groups.filter((group) => !digests.has(group.group_digest)),
    ],
    hidden: next.hidden,
    next_cursor: next.next_cursor,
  };
}

/** Whether `ids` are exactly the group's cards, in any order. */
export function wholeGroup(group: SuggestionGroup, ids: readonly string[]) {
  return (
    ids.length === group.suggestion_ids.length &&
    ids.every((id) => group.suggestion_ids.includes(id))
  );
}

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() !== "" ? value.trim() : undefined;

/** A calendar day ("2026-11-27") in the owner's words ("fre 27 nov"). */
function dayText(day: string, locale: string): string {
  const [y, m, d] = day.split("-").map(Number);
  if (!y || !m || !d) return day;
  // Noon UTC is the same calendar day in every zone the owner may live in.
  const at = new Date(Date.UTC(y, m - 1, d, 12));
  return ownerDateFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(at);
}

/** A moment ("2026-11-30T06:00:00Z") as a day in the owner's zone. */
export function momentDay(at: string, locale: string): string {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return at;
  return ownerDateFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(when);
}

/**
 * What approving would set, from the payload's own fields, in the order a person reads them. The field that names the
 * record (a Task's title, a Contact's name) is in the card's title and not repeated. A Project is named only as "in a
 * project": the app does not read another record to name it.
 */
export function payloadChanges(
  detail: Pick<SuggestionDetail, "effect" | "payload">,
  t: SuggestionLabels,
): DecisionChange[] {
  const payload = detail.payload;
  const changes: DecisionChange[] = [];
  const add = (label: string, value: string | undefined) => {
    if (value !== undefined) changes.push({ label, value });
  };
  if (detail.effect === "create_task") {
    const due = text(payload.due_on);
    add(t.fields.due_on, due ? dayText(due, t.dateLocale) : undefined);
    const priority = text(payload.priority);
    if (priority && priority !== "normal")
      add(t.fields.priority, t.priorities[priority] ?? priority);
    if (text(payload.project_id)) add(t.fields.project, t.inAProject);
    add(t.fields.description, text(payload.description));
  } else {
    add(t.fields.role, text(payload.role));
    add(t.fields.organization, text(payload.organization));
    add(t.fields.email, text(payload.email));
    add(t.fields.phone, text(payload.phone));
    add(t.fields.context_note, text(payload.context_note));
  }
  return changes;
}

/** The field of a datapoint that says what it is, by kind (as the server requires it). */
const MAIN_FIELD: Record<string, string> = {
  person: "name",
  organisation: "name",
  event: "title",
  commitment: "what",
  request: "what",
  note: "text",
};

/**
 * The untrusted text a suggestion rests on, one quote per source fact, with the label that says where it comes from.
 * The fact's main field first, then its other text fields; a flag field (`is_sender`) is not text. At most three.
 */
export function sourceQuotes(
  detail: Pick<SuggestionDetail, "datapoints" | "source_label">,
  t: SuggestionLabels,
): { label: string; text: string }[] {
  const quotes = detail.datapoints.slice(0, 3).map((point) => {
    const fields = point.fields ?? {};
    const main = MAIN_FIELD[point.kind];
    const values = [
      main ? text(fields[main]) : undefined,
      ...Object.entries(fields)
        .filter(([key]) => key !== main)
        .map(([, value]) => text(value)),
    ].filter((value): value is string => value !== undefined);
    const source = text(point.source_label);
    return {
      label: t.quoteFrom[point.source_kind],
      text: [source, values.join(" · ")].filter(Boolean).join("\n"),
    };
  });
  const quoted = quotes.filter((quote) => quote.text !== "");
  if (quoted.length > 0) return quoted;
  const label = text(detail.source_label);
  return label ? [{ label: t.quoteFrom.api, text: label }] : [];
}

/** Where an applied suggestion's record is: its Task or its Contact. */
export function appliedTarget(
  applied: { id: string; kind: string } | null | undefined,
  label?: string,
): RoomTarget | undefined {
  if (!applied) return undefined;
  if (applied.kind === "task")
    return { room: "work", view: "task", id: applied.id, label };
  if (applied.kind === "contact")
    return { room: "contacts", view: "contact", id: applied.id, label };
  return undefined;
}

/** The card's own receipt line after an approval ("Tillagd: Lena Holm"). */
export function addedLine(
  effect: SuggestionItem["effect"],
  summary: string,
  t: SuggestionLabels,
): string {
  const value = suggestionValue(effect, summary);
  return effect === "create_task" ? t.addedTask(value) : t.addedContact(value);
}
