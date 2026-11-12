import { describe, expect, it } from "vitest";

import { readStylesheet } from "./helpers/stylesheet";

// Touch targets (designsystem §2 Träffytor): touch targets measured in a real browser are
// 48 high in fullscreen and never reach into another control. These pin the CSS that gives them that, so a later
// change cannot quietly bring back the overlaps and the 44 px targets that measuring once found. Each rule is
// looked up by its selector and compared declaration by declaration; the pixel result is measured by the
// Playwright specs under tests/e2e (layout-mcp-app.spec.ts).
const NARROW_FRAME = "@container sk-frame (max-width: 17.25rem)";

describe("touch targets", () => {
  it("keeps a held shopping row's Undo target inside its own row", () => {
    const shopping = readStylesheet("features/shopping-app/shopping.css");

    // The title stays 13 down (centre 24) and Undo starts 4 down, so its target (4 past every edge) starts on the
    // row top (the row is a button beside the ring; its first line starts at --shopping-row-top, 13 at 100 % text).
    expect(
      shopping.rule(".sidekick-shopping .shopping-store-line")[
        "--shopping-row-top"
      ],
    ).toMatch(/^max\(11px, calc\(\(48px - var\(--sk-type-row-line\)\) \/ 2\)/);
    expect(
      shopping.rule(".sidekick-shopping .shopping-held-item > .shopping-undo")[
        "margin-top"
      ],
    ).toBe("calc((var(--sk-tap-lg) - var(--sk-compact)) / 2)");
  });

  it("keeps the room bar's air and Kontroll's tabs 48 high (the strip, Work's tabs and Back are measured in layout-mcp-app.spec.ts)", () => {
    const shell = readStylesheet("features/mcp-apps/sidekick-shell.css");

    // The bar owns the frame's 8 of top pad (margin -8, padding 8), and the target runs from the bar's top
    // edge to the strip's foot: 8 + 40 = 48, at rest and stuck alike. Large text drops the bar's margin and padding.
    expect(shell.rule(".sk-rooms__bar")).toMatchObject({
      "margin-top": "calc(-1 * var(--sk-s2))",
      padding: "var(--sk-s2) 0 0",
    });
    expect(shell.rule(".sk-rooms__bar", [NARROW_FRAME])).toMatchObject({
      "margin-top": "0",
      "padding-top": "0",
    });
    // The rooms' target is the ::after over each tab: from the bar's top (12 above the tab) to the strip's foot
    // (4 below), 48 with the 32 tab. Its box is 32, so a measurement of the box alone reads under 44; this pins
    // the 48.
    expect(shell.rule(".sk-rooms .sk-rooms__tab::after")).toMatchObject({
      content: '""',
      position: "absolute",
      inset: "calc(-1 * var(--sk-s1) - var(--sk-s2)) 0 calc(-1 * var(--sk-s1))",
    });
    expect(
      readStylesheet("features/control-app/control.css").rule(
        ".sidekick-control .sk-segmented .sk-segmented__option",
      ),
    ).toMatchObject({
      flex: "1 0 0",
      "min-width": "max-content",
      height: "48px",
      "min-height": "48px",
      margin: "-4px 0 -1px",
      padding: "6px var(--sk-s3) 0",
    });
  });

  it("puts the room head's icons 48 apart with 48 wide targets, and keeps Kontakter's + off the search field", () => {
    const tabs = readStylesheet("features/work-app/shell/view-tabs.css");
    const contacts = readStylesheet("features/work-app/contacts/contacts.css");

    expect(
      tabs.rule(".sidekick-work :is(.work-tab-tool, .work-tab-slot)")[
        "margin-inline-start"
      ],
    ).toBe("var(--sk-s1)");
    expect(
      tabs.rule(".sidekick-work .sk-shell-tabs-end .work-tab-tool::after")[
        "inset-inline"
      ],
    ).toBe("-2px");
    // The search field is 48 high: a 40 surface with a clear 4 px border above and under. It ends 4 before the +
    // box, so the hairline stays 7 under the surface.
    expect(
      contacts.rule(
        ".sidekick-work .work-contacts-head > .work-contacts-search",
      ),
    ).toMatchObject({
      height: "var(--sk-tap-lg)",
      margin: "0 var(--sk-s1) var(--sk-s1) 0",
      border: "var(--sk-s1) solid transparent",
      "border-inline": "0",
    });
    expect(
      contacts.rule(
        ".sidekick-work .work-contacts-head > :is(.work-contacts-add, .work-contacts-more)::after",
      ).inset,
    ).toBe("-2px");
  });

  it("lets the ring take the leading column in the row's height in the Agenda and on the board", () => {
    expect(
      readStylesheet("features/work-app/agenda/agenda.css").rule(
        ".sidekick-work .work-agenda-line > button.work-agenda-glyph",
      )["align-self"],
    ).toBe("stretch");
    expect(
      readStylesheet("features/work-app/shell/work.css").rule(
        '.sidekick-work .work-board[data-layout="single"] .work-list > li.work-card > .work-card-head > button.work-card-done::after',
      ),
    ).toMatchObject({ "z-index": "1", "inset-block": "0" });
  });

  it("gives Kontroll's rows the row template: --sk-row-pad over and under, a 48 floor, the action across both lines, and no margin on the meta line", () => {
    const control = readStylesheet("features/control-app/control.css");
    const row = control.rule(".sidekick-control .control-row");
    const secondary = control.rule(".sidekick-control .control-row-secondary");

    expect(row).toMatchObject({
      display: "grid",
      padding: "var(--sk-row-pad) 0",
      "min-height": "var(--sk-row-min)",
      "align-items": "center",
    });
    // The old row-in-room margin (0.5rem between rows) is gone: the row's own padding separates the rows.
    expect(control.has(".sk-rooms__pane .sidekick-control .control-row")).toBe(
      false,
    );
    expect(secondary["margin-top"]).toBeUndefined();
    // One meta line, cut with an ellipsis.
    expect(secondary).toMatchObject({
      "white-space": "nowrap",
      "text-overflow": "ellipsis",
    });
    // The action stands in the second column across both rows, centred on the row.
    expect(
      control.rule(".sidekick-control .control-row-action")["grid-area"],
    ).toBe("1 / 2 / 3");
  });
});
