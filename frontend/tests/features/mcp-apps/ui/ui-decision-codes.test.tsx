import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionCard } from "@/features/mcp-apps/ui/decision-card";
import {
  APPLY_ERRORS,
  CHECK_REASONS,
  decisionTrust,
  SCREENING_FLAGS,
  SUSPICIOUS_FLAGS,
} from "@/features/mcp-apps/ui/decision-codes";
import { decisionEn, decisionSv } from "@/features/mcp-apps/ui/decision-labels";

const checked = (extra: object = {}) => ({
  check_state: "checked" as const,
  verdict: "ok" as const,
  confidence: 94,
  screening_flags: [],
  reason_codes: [],
  ...extra,
});

describe("decision codes", () => {
  it("has a sentence in both languages for every flag, reason and apply error the server sends", () => {
    for (const labels of [decisionSv, decisionEn]) {
      for (const flag of SCREENING_FLAGS)
        expect(labels.flags[flag], flag).toMatch(/\.$/);
      for (const code of CHECK_REASONS.filter((code) => code !== "other"))
        expect(labels.checkReasons[code], code).toMatch(/\.$/);
      for (const code of APPLY_ERRORS)
        expect(labels.applyErrors[code], code).toMatch(/\.$/);
    }
    expect(Object.keys(decisionSv.flags)).toEqual([...SCREENING_FLAGS]);
    expect(Object.keys(decisionEn.flags)).toEqual([...SCREENING_FLAGS]);
  });

  it("reads a checked, flag-free ok as checked with the checker's confidence", () => {
    expect(decisionTrust(checked(), "sv-SE")).toEqual({
      state: "ok",
      confidence: 94,
    });
    expect(decisionTrust(checked({ confidence: null }), "sv-SE")).toEqual({
      state: "ok",
    });
  });

  it("reads a check that is off, queued or failed as not checked, with no confidence", () => {
    for (const check_state of ["off", "queued", "failed"] as const)
      expect(
        decisionTrust({ check_state, verdict: "ok", confidence: 99 }, "sv-SE"),
      ).toEqual({ state: "off" });
    // A warning verdict left from an earlier check still warns when the next check failed.
    expect(
      decisionTrust(
        {
          check_state: "failed",
          verdict: "suspicious",
          reason_codes: ["out_of_scope"],
        },
        "sv-SE",
      ),
    ).toEqual({
      state: "suspicious",
      reason: "Det ligger utanför vad automationen är till för.",
    });
  });

  it("makes an uncertain verdict, or any flag that is not suspicious, unsure with the reason in words", () => {
    expect(
      decisionTrust(
        checked({ verdict: "uncertain", reason_codes: ["duplicate_likely"] }),
        "sv-SE",
      ),
    ).toEqual({ state: "unsure", reason: "Du har redan något likadant." });
    // A flag counts with the checker off as well, and an ok verdict does not hide it.
    expect(
      decisionTrust(
        { check_state: "off", screening_flags: ["contains_link"] },
        "en-GB",
      ),
    ).toEqual({ state: "unsure", reason: "The suggestion contains a link." });
    expect(
      decisionTrust(checked({ screening_flags: ["large_batch"] }), "sv-SE")
        .state,
    ).toBe("unsure");
    // A flag the app does not know yet still keeps the card out of "ok", with no sentence.
    expect(
      decisionTrust(checked({ screening_flags: ["new_flag_v2"] }), "sv-SE"),
    ).toEqual({ state: "unsure" });
    expect(
      decisionTrust(
        checked({
          screening_flags: ["constructor"],
          reason_codes: ["toString"],
        }),
        "sv-SE",
      ),
    ).toEqual({ state: "unsure" });
  });

  it("makes a suspicious verdict or a suspicious flag suspicious, its own sentences first and each once", () => {
    for (const flag of SUSPICIOUS_FLAGS)
      expect(
        decisionTrust({ check_state: "off", screening_flags: [flag] }, "sv-SE")
          .state,
        flag,
      ).toBe("suspicious");
    expect(
      decisionTrust(
        checked({
          verdict: "suspicious",
          confidence: 8,
          screening_flags: ["contains_link", "payment_related"],
          reason_codes: ["payment_related", "out_of_scope", "other"],
        }),
        "sv-SE",
      ),
    ).toEqual({
      state: "suspicious",
      reason: "Förslaget handlar om en betalning.",
      reasons: [
        "Förslaget handlar om en betalning.",
        "Förslaget innehåller en länk.",
        "Det ligger utanför vad automationen är till för.",
      ],
    });
    expect(decisionTrust(checked({ verdict: "suspicious" }), "sv-SE")).toEqual({
      state: "suspicious",
    });
  });
});

describe("DecisionCard with the server's fields", () => {
  const actions = () => ({ approve: vi.fn(), dismiss: vi.fn() });

  it("says in the kicker that the owner edited the suggestion", () => {
    render(
      <DecisionCard
        locale="sv-SE"
        kicker="Förslag"
        title="Skapa kontakt: Lena Holm"
        source={{ name: "Morgonmejl", at: "07:02" }}
        edited
        actions={actions()}
      />,
    );
    expect(
      screen.getByRole("article", { name: "Skapa kontakt: Lena Holm" }),
    ).toHaveTextContent("Förslag · från Morgonmejl · 07:02 · ändrad av dig");
  });

  it("puts the server's refusal in words under the answers, in both languages", () => {
    const { rerender } = render(
      <DecisionCard
        locale="sv-SE"
        kicker="Förslag"
        title="Skapa uppgift: Ring Karin"
        failed="approve"
        applyError="project_gone"
        actions={actions()}
      />,
    );
    const card = () =>
      screen.getByRole("article", { name: "Skapa uppgift: Ring Karin" });
    expect(card()).toHaveTextContent(decisionSv.applyErrors.project_gone);
    expect(card()).not.toHaveTextContent(decisionSv.failedApprove);
    rerender(
      <DecisionCard
        locale="en-GB"
        kicker="Suggestion"
        title="Skapa uppgift: Ring Karin"
        failed="approve"
        applyError="conflict"
        actions={actions()}
      />,
    );
    expect(card()).toHaveTextContent(decisionEn.applyErrors.conflict);
    // A failed dismissal has no apply error: the general line stays.
    rerender(
      <DecisionCard
        locale="sv-SE"
        kicker="Förslag"
        title="Skapa uppgift: Ring Karin"
        failed="dismiss"
        applyError="conflict"
        actions={actions()}
      />,
    );
    expect(card()).toHaveTextContent(decisionSv.failedDismiss);
  });

  it("shows the first reason inline and every reason in the detail", () => {
    const trust = decisionTrust(
      checked({
        verdict: "suspicious",
        screening_flags: ["contains_link", "payment_related"],
      }),
      "en-GB",
    );
    const { rerender } = render(
      <DecisionCard
        locale="en-GB"
        kicker="Suggestion"
        title="Create task: Pay the new invoice"
        trust={trust}
        actions={{ ...actions(), review: vi.fn() }}
      />,
    );
    const note = () => screen.getByRole("note");
    expect(note()).toHaveTextContent(
      "Suspicious suggestion: The suggestion is about a payment.",
    );
    expect(note()).not.toHaveTextContent("link");
    rerender(
      <DecisionCard
        locale="en-GB"
        kicker="Suggestion"
        title="Create task: Pay the new invoice"
        trust={trust}
        density="full"
        actions={actions()}
      />,
    );
    expect(note()).toHaveTextContent(
      "The suggestion is about a payment. The suggestion contains a link.",
    );
  });

  it("draws a suspicious card from its codes with the warning in words and no Approve", () => {
    render(
      <DecisionCard
        locale="sv-SE"
        kicker="Förslag"
        title="Skapa uppgift: Betala fakturan till nya kontot"
        trust={decisionTrust(
          checked({
            verdict: "suspicious",
            screening_flags: ["payment_related"],
          }),
          "sv-SE",
        )}
        actions={{ ...actions(), review: vi.fn() }}
      />,
    );
    const card = screen.getByRole("article");
    expect(within(card).getByRole("note")).toHaveTextContent(
      "Misstänkt förslag: Förslaget handlar om en betalning.",
    );
    expect(
      within(card).queryByRole("button", { name: "Godkänn" }),
    ).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Granska" })).toBeVisible();
  });
});
