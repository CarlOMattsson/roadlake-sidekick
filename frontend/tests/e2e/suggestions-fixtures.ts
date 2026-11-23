/**
 * Suggestions in the shape the server's tools answer (list_suggestions, get_suggestion, decide_suggestions,
 * approve_suggestion_group, undo_suggestion), for the simulated host. The summary is the server's English line; the
 * app puts it in its own language. Synthetic data only.
 */
import type { ToolResults } from "../../src/lib/mcp/tool-results.generated";

type Page = ToolResults["list_suggestions"];
type Item = Page["items"][number];
type Detail = ToolResults["get_suggestion"]["suggestion"];

export const sid = (n: number) =>
  `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`;
const automationId = sid(800);

const safeCheck = (confidence: number): Item["check"] => ({
  state: "checked",
  verdict: "ok",
  confidence,
});

function item(n: number, partial: Partial<Item>): Item {
  return {
    apply_error: null,
    automation_id: automationId,
    automation_title: "Morgonmejl",
    bulk_eligible: false,
    check: { state: "off", verdict: null, confidence: null },
    edited: false,
    effect: "create_task",
    expires_at: "2026-11-30T06:00:00Z",
    flags: [],
    id: sid(n),
    source_label: null,
    state: "pending",
    summary: "Create task: Untitled",
    version: 1,
    ...partial,
  };
}

/** Four safe ones in one group (more than one confirmation takes), then three to review alone. */
export const groupItems: Item[] = [
  item(1, {
    summary: "Create task: Ring Karin om offerten",
    bulk_eligible: true,
    check: safeCheck(94),
  }),
  item(2, {
    effect: "create_contact",
    summary: "Create contact: Maja Berg",
    bulk_eligible: true,
    check: safeCheck(97),
  }),
  item(3, {
    summary: "Create task: Boka plattsättaren",
    bulk_eligible: true,
    check: safeCheck(95),
  }),
  item(4, {
    summary: "Create task: Beställ kakel till badrummet",
    bulk_eligible: true,
    check: safeCheck(92),
  }),
];

export const reviewItems: Item[] = [
  item(5, {
    effect: "create_contact",
    summary: "Create contact: Lena Holm",
    check: { state: "checked", verdict: "uncertain", confidence: 61 },
    flags: ["duplicate_existing"],
  }),
  item(6, {
    summary: "Create task: Betala ny faktura",
    check: { state: "checked", verdict: "suspicious", confidence: 8 },
    flags: ["contains_link", "payment_related"],
  }),
  item(7, {
    summary: "Create task: Svara Erik om hyresgästen",
    automation_title: "Kvällsgenomgång",
  }),
];

export const inboxPage: Page = {
  groups: [
    {
      automation_id: automationId,
      automation_title: "Morgonmejl",
      count: groupItems.length,
      group_digest: "a".repeat(64),
      suggestion_ids: groupItems.map((entry) => entry.id),
    },
  ],
  hidden: 0,
  items: [...groupItems, ...reviewItems],
  next_cursor: null,
};

export const emptyPage: Page = {
  groups: [],
  hidden: 0,
  items: [],
  next_cursor: null,
};

function detailOf(entry: Item, partial: Partial<Detail> = {}): Detail {
  return {
    ...entry,
    applied: null,
    blockers: entry.bulk_eligible ? [] : ["not_checked"],
    checks: [],
    datapoints: [],
    decided_at: null,
    decided_by: null,
    decision_channel: null,
    payload: {},
    rationale: "",
    undone_at: null,
    ...partial,
  };
}

export const details: Record<string, Detail> = {
  [sid(5)]: detailOf(reviewItems[0]!, {
    payload: {
      display_name: "Lena Holm",
      role: "Projektledare",
      organization: "Holm Bygg",
      email: "lena.holm@example.org",
    },
    rationale: "Lena skrev under mejlet om köket.",
    blockers: ["verdict_not_ok", "flagged"],
    checks: [
      {
        attempt: 1,
        checked_at: "2026-11-23T06:03:00Z",
        checker: "independent",
        confidence: 61,
        model: "small",
        reason_codes: ["duplicate_likely"],
        verdict: "uncertain",
      },
    ],
    datapoints: [
      {
        id: sid(905),
        kind: "person",
        fields: {
          name: "Lena Holm",
          email: "lena.holm@example.org",
          role: "Projektledare",
        },
        source_kind: "mail",
        source_label: "Re: Köket på Storgatan",
      },
    ],
  }),
  [sid(6)]: detailOf(reviewItems[1]!, {
    payload: {
      title: "Betala ny faktura",
      due_on: "2026-11-23",
      priority: "high",
      description: "Konto SE45 5000 0000 0583 9825 7466",
    },
    rationale: "Mejlet ber om att betalningen flyttas i dag.",
    blockers: ["verdict_not_ok", "flagged"],
    checks: [
      {
        attempt: 1,
        checked_at: "2026-11-23T06:03:00Z",
        checker: "independent",
        confidence: 8,
        model: "small",
        reason_codes: ["out_of_scope"],
        verdict: "suspicious",
      },
    ],
    datapoints: [
      {
        id: sid(906),
        kind: "request",
        fields: {
          what: "Flytta betalningen till det nya kontot i dag, se https://pay.example.net/x?id=9 före kl. 17.",
        },
        source_kind: "mail",
        source_label: "Brådskande: ny bankinformation",
      },
    ],
  }),
  [sid(7)]: detailOf(reviewItems[2]!, {
    payload: { title: "Svara Erik om hyresgästen", due_on: "2026-11-25" },
    rationale: "Erik väntar på besked sedan i fredags.",
  }),
};

const reply = (structuredContent: unknown) => ({ structuredContent });

/** The host's answers: the inbox, each card by id, and decisions that succeed. */
export const suggestionReplies = {
  list_suggestions: reply(inboxPage),
  get_suggestion: {
    __byArgument: {
      key: "suggestion_id",
      answers: Object.fromEntries(
        Object.entries(details).map(([id, detail]) => [
          id,
          reply({ suggestion: detail }),
        ]),
      ),
    },
  },
  decide_suggestions: reply({
    items: [
      {
        suggestion_id: sid(7),
        state: "applied",
        version: 2,
        error_code: null,
        applied: { id: sid(707), kind: "task" },
      },
    ],
  }),
  approve_suggestion_group: reply({
    items: [1, 2, 3].map((n) => ({
      suggestion_id: sid(n),
      state: "applied",
      version: 2,
      error_code: null,
      applied: { id: sid(700 + n), kind: n === 2 ? "contact" : "task" },
    })),
  }),
  undo_suggestion: reply({
    suggestion_id: sid(7),
    state: "undone",
    version: 3,
    trashed: { id: sid(707), kind: "task" },
  }),
};

/** decide_suggestions for the first three of the group, each applied. */
export const groupDecided = reply({
  items: [1, 2, 3].map((n) => ({
    suggestion_id: sid(n),
    state: "applied",
    version: 2,
    error_code: null,
    applied: { id: sid(700 + n), kind: n === 2 ? "contact" : "task" },
  })),
});
