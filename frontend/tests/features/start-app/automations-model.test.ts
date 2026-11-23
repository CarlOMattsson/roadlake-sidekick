import { describe, expect, it } from "vitest";

import {
  automationLabelsFor,
  automationsEn,
  automationsSv,
} from "@/features/start-app/automations/labels";
import {
  approvalNeed,
  approveArguments,
  autoApplyLimits,
  automationIdOf,
  MAX_AUTO_PER_DAY,
  MAX_AUTO_PER_RUN,
  countsLine,
  factsOf,
  highlightText,
  isAutomationPage,
  isAutomationResult,
  listOrder,
  reportOf,
  rowMeta,
  scheduleText,
  stateOf,
} from "@/features/start-app/automations/model";
import {
  automationsPage,
  evening,
  invoices,
  morning,
  report,
  weekly,
} from "../../e2e/automations-fixtures";

const sv = automationLabelsFor("sv");
const en = automationLabelsFor("en");

function keysOf(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, entry]) =>
    entry && typeof entry === "object" && !Array.isArray(entry)
      ? keysOf(entry as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("the automations' texts", () => {
  it("have the same keys in Swedish and English", () => {
    expect(keysOf(automationsSv).sort()).toEqual(keysOf(automationsEn).sort());
  });

  it("are Swedish unless the locale is English", () => {
    expect(automationLabelsFor("fr").title).toBe("Automationer");
    expect(automationLabelsFor("en-GB").title).toBe("Automations");
  });

  it("end the receipt without a full stop", () => {
    for (const t of [sv, en]) expect(t.approvedReceipt("X")).not.toMatch(/\.$/);
  });
});

describe("autoApplyLimits", () => {
  it("reads the caps from the record the server answered", () => {
    expect(
      autoApplyLimits({ auto_apply_limits: { per_run: 3, per_day: 7 } }),
    ).toEqual({ perRun: 3, perDay: 7 });
  });

  it("falls back to the constants when the answer has none", () => {
    expect(autoApplyLimits({})).toEqual({
      perRun: MAX_AUTO_PER_RUN,
      perDay: MAX_AUTO_PER_DAY,
    });
    expect(autoApplyLimits({ auto_apply_limits: {} })).toEqual({
      perRun: 10,
      perDay: 25,
    });
  });
});

describe("approveArguments", () => {
  it("sends the digest exactly as shown, and no confirmation for a spec that only proposes", () => {
    const args = approveArguments(morning, false, "k1");
    expect(args).toEqual({
      automation_id: morning.id,
      spec_digest: morning.spec_digest,
      idempotency_key: "k1",
    });
    // A confirmation given by mistake is never sent for a spec that does not apply anything by itself.
    expect(approveArguments(morning, true, "k1")).not.toHaveProperty(
      "auto_apply_confirmed",
    );
  });

  it("sends nothing for a spec that applies without a click until the owner confirmed it", () => {
    expect(approveArguments(invoices, false, "k2")).toBeUndefined();
    expect(approveArguments(invoices, true, "k2")).toEqual({
      automation_id: invoices.id,
      spec_digest: invoices.spec_digest,
      idempotency_key: "k2",
      auto_apply_confirmed: true,
    });
  });
});

describe("approvalNeed", () => {
  it("says what the approval asks of the owner", () => {
    expect(approvalNeed(morning)).toEqual({
      kind: "approved",
      auto: false,
      paused: false,
      at: morning.approved_at,
    });
    expect(approvalNeed(invoices)).toEqual({
      kind: "approve",
      auto: true,
      changed: false,
    });
    expect(approvalNeed(evening)).toEqual({
      kind: "approve",
      auto: false,
      changed: true,
    });
    expect(approvalNeed(weekly)).toMatchObject({
      kind: "approved",
      paused: true,
    });
    expect(approvalNeed({ ...invoices, state: "archived" })).toEqual({
      kind: "archived",
    });
  });

  it("offers no approval the server would refuse for a missing source or effect", () => {
    expect(
      approvalNeed({ ...invoices, sources: [], allowed_effects: [] }),
    ).toEqual({ kind: "incomplete", missing: ["sources", "effects"] });
  });
});

describe("the list", () => {
  it("reads list_automations and names each state", () => {
    expect(isAutomationPage(automationsPage)).toBe(true);
    expect(automationsPage.items.map((item) => stateOf(item))).toEqual([
      "on",
      "waiting",
      "changed",
      "paused",
    ]);
  });

  it("puts the ones that wait for the owner first", () => {
    expect(listOrder(automationsPage.items).map((item) => item.title)).toEqual([
      "Fakturakoll",
      "Kvällsgenomgång",
      "Morgonmejl",
      "Veckorapport",
    ]);
  });

  it("says where a row stands, what waits and when it last ran", () => {
    expect(rowMeta(morning, sv)).toMatch(
      /^På · 3 förslag väntar · senast körd mån 23 nov\.?$/,
    );
    expect(rowMeta(invoices, sv)).toBe("Väntar på ditt godkännande");
    expect(rowMeta(evening, en)).toBe("Changed since you approved it");
  });
});

describe("one automation", () => {
  it("reads a whole record and an id-only one", () => {
    expect(isAutomationResult({ automation: morning })).toBe(true);
    expect(isAutomationResult({ automation: { id: morning.id } })).toBe(false);
    expect(automationIdOf({ automation: { id: morning.id } })).toBe(morning.id);
  });

  it("says when it runs in both languages", () => {
    expect(scheduleText(morning.cadence, sv)).toBe(
      "Varje mån, tis, ons, tors och fre kl. 07:00",
    );
    expect(scheduleText(evening.cadence, en)).toBe("Daily at 18:30");
    expect(scheduleText(null, sv)).toBe("Bara när du startar den");
  });

  it("lists the facts an approval binds in plain words", () => {
    const facts = Object.fromEntries(
      factsOf(invoices, sv).map((fact) => [fact.key, fact]),
    );
    expect(facts.sources?.value).toBe("Mejl");
    expect(facts.effects?.value).toBe("Nya uppgifter");
    expect(facts.handling?.value).toBe(
      "Lägger in nya uppgifter utan att fråga när kontrollen är minst 95 % säker",
    );
    expect(facts.limits?.value).toBe(
      "Högst 10 förslag och 0,50 USD per körning",
    );
    expect(facts.runner?.value).toBe("Sidekick på servern");
    expect(
      factsOf(morning, en).find((fact) => fact.key === "effects")?.value,
    ).toBe("New contacts and new tasks");
  });

  it("finds its runs in the report", () => {
    const own = reportOf(report, morning.id);
    expect(countsLine(own.counts!, sv)).toBe(
      "3 körningar · 1 misslyckades · 7 förslag · 3 väntar · 0,09 USD",
    );
    expect(own.highlights.map((item) => highlightText(item, sv))).toEqual([
      "Körningen misslyckades: budgeten tog slut",
    ]);
    expect(reportOf(report, invoices.id)).toEqual({
      counts: undefined,
      highlights: [],
    });
  });
});
