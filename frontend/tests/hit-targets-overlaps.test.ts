import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Touch targets (designsystem §2 Träffytor): touch targets measured in a real browser are
// 48 high in fullscreen and never reach into another control. These pin the CSS that gives them that, so a later
// change cannot quietly bring back the overlaps and the 44 px targets that measuring once found.
const css = (file: string) =>
  readFileSync(
    path.resolve(import.meta.dirname, "../src/features", file),
    "utf8",
  );

describe("touch targets", () => {
  it("keeps a held shopping row's Undo target inside its own row", () => {
    const shopping = css("shopping-app/shopping.css");
    // The title stays 13 down (centre 24) and Undo starts 4 down, so its target (4 past every edge) starts on the row top.
    // (the row is a button beside the ring; its first line starts at --shopping-row-top, 13 at 100 % text.)
    expect(shopping).toMatch(
      /\.shopping-store-line \{\s*--shopping-row-top: max\(\s*11px,\s*calc\(\(48px - var\(--sk-type-row-line\)\) \/ 2\)/,
    );
    expect(shopping).toMatch(
      /\.shopping-held-item > \.shopping-undo \{[^}]*margin-top: calc\(\(var\(--sk-tap-lg\) - var\(--sk-compact\)\) \/ 2\);/,
    );
  });

  it("keeps the room bar's air and Kontroll's tabs 48 high (the strip, Work's tabs and Back are measured in layout-mcp-app.spec.ts)", () => {
    // The bar owns the frame's 8 of top pad (margin -8, padding 8), and the target runs from the bar's top
    // edge to the strip's foot: 8 + 40 = 48, at rest and stuck alike. Large text drops the bar's margin and padding.
    const shell = css("mcp-apps/sidekick-shell.css");
    expect(shell).toMatch(
      /\.sk-rooms__bar \{[^}]*margin-top: calc\(-1 \* var\(--sk-s2\)\);\s*padding: var\(--sk-s2\) 0 0;/,
    );
    expect(shell).toMatch(
      /@container sk-frame \(max-width: 17\.25rem\) \{[^}]*\.sk-rooms__bar \{[^}]*margin-top: 0;\s*padding-top: 0;/,
    );
    // The rooms' target is the ::after over each tab: from the bar's top (12 above the tab) to the strip's foot (4 below),
    // 48 with the 32 tab. Its box is 32, so a measurement of the box alone reads under 44; this pins the 48.
    expect(shell).toMatch(
      /\.sk-rooms \.sk-rooms__tab::after \{\s*content: "";\s*position: absolute;\s*inset: calc\(-1 \* var\(--sk-s1\) - var\(--sk-s2\)\) 0 calc\(-1 \* var\(--sk-s1\)\);/,
    );
    expect(css("control-app/control.css")).toMatch(
      /\.sk-segmented__option \{\s*flex: 1 0 0;\s*min-width: max-content;\s*height: 48px;\s*min-height: 48px;\s*margin: -4px 0 -1px;\s*padding: 6px var\(--sk-s3\) 0;/,
    );
  });

  it("puts the room head's icons 48 apart with 48 wide targets, and keeps Kontakter's + off the search field", () => {
    const tabs = css("work-app/view-tabs.css");
    expect(tabs).toMatch(
      /:is\(\.work-tab-tool, \.work-tab-slot\) \{[^}]*margin-inline-start: var\(--sk-s1\);/,
    );
    expect(tabs).toMatch(
      /\.sk-shell-tabs-end \.work-tab-tool::after \{[^}]*inset-inline: -2px;/,
    );
    const contacts = css("work-app/contacts.css");
    // The search field is 48 high: a 40 surface with a clear 4 px border above and under. It ends 4 before the +
    // box, so the hairline stays 7 under the surface.
    expect(contacts).toMatch(
      /\.work-contacts-search \{[^}]*height: var\(--sk-tap-lg\);[^}]*margin: 0 var\(--sk-s1\) var\(--sk-s1\) 0;[^}]*border: var\(--sk-s1\) solid transparent;[^}]*border-inline: 0;/,
    );
    expect(contacts).toMatch(
      /:is\(\.work-contacts-add, \.work-contacts-more\)::after \{[^}]*inset: -2px;/,
    );
  });

  it("lets the ring take the leading column in the row's height in the Agenda and on the board", () => {
    expect(css("work-app/agenda.css")).toMatch(
      /\.work-agenda-line > button\.work-agenda-glyph \{[^}]*align-self: stretch;/,
    );
    expect(css("work-app/work.css")).toMatch(
      /button\.work-card-done::after \{[^}]*z-index: 1;[^}]*inset-block: 0;/,
    );
  });

  it("gives Kontroll's rows the row template: --sk-row-pad over and under, a 48 floor, the action across both lines, and no margin on the meta line", () => {
    const control = css("control-app/control.css");
    const row = /\.sidekick-control \.control-row \{([^}]*)\}/.exec(
      control,
    )?.[1];
    expect(row, "control row rule").toBeDefined();
    expect(row).toMatch(/display: grid;/);
    expect(row).toMatch(/padding: var\(--sk-row-pad\) 0;/);
    expect(row).toMatch(/min-height: var\(--sk-row-min\);/);
    // The old row-in-room margin (0.5rem between rows) is gone: the row's own padding separates the rows.
    expect(control).not.toMatch(
      /\.sk-rooms__pane \.sidekick-control \.control-row \{/,
    );
    const secondary =
      /\.sidekick-control \.control-row-secondary \{([^}]*)\}/.exec(
        control,
      )?.[1];
    expect(secondary, "control row meta rule").toBeDefined();
    expect(secondary).not.toMatch(/margin-top/);
    // One meta line, cut with an ellipsis.
    expect(secondary).toMatch(/white-space: nowrap;/);
    expect(secondary).toMatch(/text-overflow: ellipsis;/);
    // The action stands in the second column across both rows, centred on the row.
    const action = /\.sidekick-control \.control-row-action \{([^}]*)\}/.exec(
      control,
    )?.[1];
    expect(action).toMatch(/grid-area: 1 \/ 2 \/ 3;/);
    expect(row).toMatch(/align-items: center;/);
  });
});
