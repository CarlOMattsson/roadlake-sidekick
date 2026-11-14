// What of the MCP apps' design language (docs/reference/design-system.md) is still checked from the stylesheet text.
// The rules about the source (tokens defined, reduced motion, no px font sizes, 44 px buttons) are in
// css-policy.test.ts, and how the views look is measured in a browser (tests/e2e/ui-family-styles-mcp-app.spec.ts,
// journal-styles-mcp-app.spec.ts and the specs beside them). The two rules below have no browser check yet: a chosen chip
// needs a writable priority chip, and the Shopping inline card is a card the simulated host does not open (it opens
// the Shopping room); both are stylesheet rules that stay.
import { describe, expect, it } from "vitest";

import { cssRules, loadCssFiles, valueOf } from "./helpers/css-contract";

const files = [
  "mcp-apps/ui",
  "work-app",
  "shopping-app",
  "control-app",
].flatMap(loadCssFiles);

// Body of the top-level rule that lists this selector (the whole list or one part of it) in one stylesheet. Fails the
// test when the rule is missing, so a renamed selector cannot pass silently.
function ruleBody(rel: string, selector: string): string {
  const file = files.find((entry) => entry.rel === rel);
  expect(file, rel).toBeDefined();
  const rule = cssRules(file?.css ?? "").find(
    (candidate) =>
      candidate.selector === selector ||
      candidate.selector.split(",").some((part) => part.trim() === selector),
  );
  expect(rule, `${rel} ${selector}`).toBeDefined();
  return rule?.body ?? "";
}

describe("MCP-app UI CSS contract", () => {
  it("a chosen chip has the 2 px outline in the text colour, the selected fill and a tick", () => {
    const pressed = ruleBody(
      "mcp-apps/ui/family.css",
      ':is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control) button.sk-chip[aria-pressed="true"], .sk-chip[aria-pressed="true"]',
    );
    expect(valueOf(pressed, "border-color")).toBe("var(--sk-selected-line)");
    expect(valueOf(pressed, "background")).toBe("var(--sk-selected-bg)");
    // The 1 px edge plus (2 - 1) px inside it is the 2 px contour (--sk-selected-width), so nothing moves.
    expect(valueOf(pressed, "box-shadow")?.replace(/\s+/g, " ")).toBe(
      "inset 0 0 0 calc(var(--sk-selected-width) - var(--sk-hairline)) var(--sk-selected-line)",
    );
    expect(valueOf(pressed, "font-weight")).toBe("var(--sk-weight-semibold)");
    const tick = ruleBody(
      "mcp-apps/ui/family.css",
      '.sk-chip[aria-pressed="true"]::before',
    );
    expect(valueOf(tick, "-webkit-mask")).toContain("var(--sk-check)");
  });

  it("the Shopping inline card grows with its content: height is auto, not a fixed height", () => {
    const body = ruleBody("shopping-app/shopping.css", ".shopping-card-body");
    expect(valueOf(body, "height")).toBe("auto");
  });
});
