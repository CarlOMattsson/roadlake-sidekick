import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkShell, type WorkShellProps } from "@/features/work-app/work-shell";
import {
  workShellLabelsEn,
  workShellLabelsFor,
  workShellLabelsSv,
} from "@/features/work-app/work-shell-labels";

function panels(): Pick<WorkShellProps, "agenda" | "board" | "hierarchy"> {
  return {
    agenda: <p>Innehåll agenda</p>,
    board: <p>Innehåll board</p>,
    hierarchy: <p>Innehåll hierarki</p>,
  };
}

describe.each([
  {
    name: "sv",
    labels: workShellLabelsSv,
    group: "Vyer",
    tabs: ["Agenda", "Status", "Projekt"],
  },
  {
    name: "en",
    labels: workShellLabelsEn,
    group: "Views",
    tabs: ["Agenda", "Status", "Projects"],
  },
])("WorkShell ($name)", ({ labels, group, tabs }) => {
  it("shows the tab strip in order, opens on Agenda, and shows only that tab's content", () => {
    render(<WorkShell labels={labels} {...panels()} />);

    const strip = screen.getByRole("group", { name: group });
    const buttons = within(strip).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(tabs);
    expect(screen.getByRole("button", { name: tabs[0] })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll agenda")).toBeInTheDocument();
    expect(screen.queryByText("Innehåll board")).not.toBeInTheDocument();
    expect(screen.queryByText("Innehåll hierarki")).not.toBeInTheDocument();
  });

  it("switches tab locally when a tab is pressed, without any callback", async () => {
    const user = userEvent.setup();
    render(<WorkShell labels={labels} {...panels()} />);

    await user.click(screen.getByRole("button", { name: tabs[1] }));

    expect(screen.getByRole("button", { name: tabs[1] })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll board")).toBeVisible();
    // Agenda was pressed on open, so it stays mounted but hidden.
    expect(screen.getByText("Innehåll agenda")).not.toBeVisible();
    expect(screen.queryByText("Innehåll hierarki")).not.toBeInTheDocument();
  });

  it("keeps a visited tab mounted and hidden, and reports each pressed tab", async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    render(
      <WorkShell labels={labels} {...panels()} onTabChange={onTabChange} />,
    );

    await user.click(screen.getByRole("button", { name: tabs[2] }));
    await user.click(screen.getByRole("button", { name: tabs[0] }));

    expect(onTabChange.mock.calls).toEqual([["hierarchy"], ["agenda"]]);
    expect(screen.getByText("Innehåll hierarki")).not.toBeVisible();
    expect(screen.getByText("Innehåll agenda")).toBeVisible();
  });

  it("opens on the tab given as initialTab", () => {
    render(<WorkShell labels={labels} initialTab="hierarchy" {...panels()} />);

    expect(screen.getByRole("button", { name: tabs[2] })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll hierarki")).toBeInTheDocument();
  });

  it("is a fullscreen frame with no detail region when no detail is given", () => {
    const { container } = render(<WorkShell labels={labels} {...panels()} />);

    expect(container.querySelector(".sk-frame")).toHaveAttribute(
      "data-mode",
      "full",
    );
    expect(container.querySelector(".sk-wide")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: labels.detailLabel }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: labels.back }),
    ).not.toBeInTheDocument();
  });

  it("shows the detail beside the list with a back button that calls onBack", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const { container } = render(
      <WorkShell
        labels={labels}
        {...panels()}
        detail={<p>Detaljtext</p>}
        onBack={onBack}
      />,
    );

    expect(container.querySelector("[data-detail]")).toHaveAttribute(
      "data-detail",
      "open",
    );
    expect(screen.getByText("Innehåll agenda")).toBeInTheDocument();
    const detailRegion = screen.getByRole("region", {
      name: labels.detailLabel,
    });
    expect(within(detailRegion).getByText("Detaljtext")).toBeInTheDocument();

    await user.click(
      within(detailRegion).getByRole("button", { name: labels.back }),
    );
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("does not show a back button when detail is given without onBack", () => {
    render(
      <WorkShell labels={labels} {...panels()} detail={<p>Detaljtext</p>} />,
    );

    expect(screen.getByText("Detaljtext")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: labels.back }),
    ).not.toBeInTheDocument();
  });
});

describe("fullscreen clearance above the host reply field", () => {
  // jsdom applies no CSS, so the rules are read from the stylesheets.
  const read = (file: string) =>
    readFileSync(path.resolve(import.meta.dirname, file), "utf8");

  it(".sk-shell adds no bottom padding (the frame keeps the foot reserve)", () => {
    const css = read("../src/features/work-app/work-shell.css");
    // --work-undo-bottom was read by nothing and is gone.
    expect(css).not.toMatch(/work-undo-bottom/);
    expect(css).not.toMatch(/\.sk-shell \{[^}]*padding-block-end/);
  });

  it("keeps the foot reserve below the frame content", () => {
    const css = read("../src/features/mcp-apps/ui/layout.css");
    expect(css).toMatch(
      /\.sk-frame\[data-mode="full"\] > \.sk-frame__body \{[^}]*padding-bottom: calc\(var\(--sk-frame-pad\) \+ var\(--sk-foot-reserve, 6rem\)\);/,
    );
  });

  it("defines the foot reserve as the larger of the host inset and 6rem", () => {
    const tokens = read("../src/features/mcp-apps/ui/tokens.css");
    expect(tokens).toMatch(
      /--sk-foot-reserve: max\(var\(--host-safe-bottom, 0px\), 6rem\);/,
    );
  });
});

describe("task detail layout at 320 px", () => {
  it("leaves the detail its 16 px page margin, and has no status segments: the status is a property chip", () => {
    // The task detail's rules live in task-detail.css (loaded right after work.css).
    const css = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/work-app/task-detail.css",
      ),
      "utf8",
    );
    // The detail has no frame of its own and adds no side padding: its 16 px side margin is the page's (the
    // fullscreen frame body, layout.css), the same as every other screen.
    expect(css).toMatch(
      /\.sidekick-work \.work-task \{\s*padding: 0;\s*border: 0;/,
    );
    const layout = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/mcp-apps/ui/layout.css",
      ),
      "utf8",
    );
    expect(layout).toMatch(/--sk-frame-pad: 16px;/);
    // The status segments are gone: the status and the due date are property chips (task-detail-controls.tsx),
    // not a radio group.
    expect(css).not.toMatch(/work-task-status/);
    const controls = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/work-app/task-detail-controls.tsx",
      ),
      "utf8",
    );
    expect(controls).not.toMatch(/role="radiogroup"/);
    expect(controls).toMatch(/className="sk-chip work-prop-chip"/);
  });

  it("sizes Markera klar to its text (a compact primary with no rule of its own), and gives each Step the row template's --sk-row-pad above and below inside its --sk-row-min", () => {
    const css = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/work-app/task-detail.css",
      ),
      "utf8",
    );
    // The button is the family's compact primary, as wide as its text; the old full-width rule is gone.
    expect(css).not.toMatch(/work-task-done/);
    const family = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/mcp-apps/ui/family.css",
      ),
      "utf8",
    );
    const compact = /\.sk-btn--compact \{([^}]*)\}/.exec(family)?.[1];
    expect(compact, "compact rule").toBeDefined();
    expect(compact).not.toMatch(/width: 100%/);
    expect(compact).toMatch(/white-space: nowrap;/);
    // It is the last control of the property row (task-detail-controls.tsx renders `done` after the chips).
    const controls = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/work-app/task-detail-controls.tsx",
      ),
      "utf8",
    );
    expect(controls).toMatch(/\)\}\s*\{done\}\s*\{onDue && open === "due"/);
    // The air lies inside the label's 48 (no ⋯), and the list rises by --sk-row-air-extra.
    expect(css).not.toMatch(/\.sidekick-work \.work-steps > li \{/);
    const step =
      /\.sidekick-work \.work-steps :is\(label, \.work-step-read\) \{([^}]*)\}/.exec(
        css,
      )?.[1];
    expect(step, "step rule").toBeDefined();
    expect(step).toMatch(/min-height: var\(--sk-row-min\);/);
    expect(step).toMatch(/padding-block: var\(--sk-row-pad\);/);
    const list = /\.sidekick-work \.work-steps \{([^}]*)\}/.exec(css)?.[1];
    expect(list).toMatch(
      /margin: calc\(-1 \* var\(--sk-row-air-extra\)\) 0 0;/,
    );
  });

  it("gives a linked Contact no ⋯ button, only a › that opens it (removal is in the row's own menu)", () => {
    const source = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/work-app/work-view-parts/task-contacts-section.tsx",
      ),
      "utf8",
    );
    const start = source.indexOf("<LinkedRow");
    expect(start).toBeGreaterThan(-1);
    const row = source.slice(start, source.indexOf("</LinkedRow>", start));
    expect(row).not.toContain("⋯");
    expect(row).not.toContain("work-row-actions");
    expect(row).toContain("<OpenChevron />");
  });
});

describe("workShellLabelsFor", () => {
  it("returns Swedish for sv locales and English for everything else", () => {
    expect(workShellLabelsFor("sv-SE")).toBe(workShellLabelsSv);
    expect(workShellLabelsFor("en-US")).toBe(workShellLabelsEn);
    expect(workShellLabelsFor("de")).toBe(workShellLabelsEn);
  });

  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(workShellLabelsSv.tabs).sort()).toEqual(
      Object.keys(workShellLabelsEn.tabs).sort(),
    );
    expect(Object.keys(workShellLabelsSv).sort()).toEqual(
      Object.keys(workShellLabelsEn).sort(),
    );
  });
});

describe("the tab row sticks under the host strip", () => {
  // jsdom applies no CSS, so the sticky rules are read from the stylesheets.
  const read = (file: string) =>
    readFileSync(path.resolve(import.meta.dirname, file), "utf8");

  it("sticks Work's tab row at the shell's sticky offset, above the list", () => {
    const css = read("../src/features/work-app/work-shell.css");
    expect(css).toMatch(
      /\.sk-shell-tabs \{[^}]*position: sticky;[^}]*top: var\(--sk-sticky-top\);[^}]*z-index: 2;/,
    );
  });

  it("gives the list the offset under the strip and the tab row, whose height is --sk-tabs-h (--sk-sticky-top)", () => {
    const css = read("../src/features/mcp-apps/sidekick-shell.css");
    expect(css).toMatch(
      /\.sk-shell-list \{\s*--sk-sticky-top: calc\(\s*var\(--host-safe-top, 0px\) \+ var\(--sk-bar-h, 0px\) \+ var\(--sk-tabs-h\)\s*\);\s*\}/,
    );
    // The tab row and its tools use the same height token, so the offset is the row's real height.
    expect(css).not.toMatch(/\.sk-shell-list \{[^}]*var\(--sk-tap\)/);
    const tabs = read("../src/features/work-app/view-tabs.css");
    expect(tabs).toMatch(/height: var\(--sk-tabs-h\);/);
    const shell = read("../src/features/work-app/work-shell.css");
    expect(shell).toMatch(/height: var\(--sk-tabs-h\);/);
    const tokens = read("../src/features/mcp-apps/ui/tokens.css");
    expect(tokens).toMatch(/--sk-tabs-h:\s*min\(var\(--sk-tap\), 56px\);/);
  });

  it("paints the stuck room strip bar and Work's tab row to the frame's side edges, one band of one width", () => {
    // The strip and the Back row keep the rooms' reading width inside the band, as the tab row's tabs do.
    const bleed =
      /margin-inline: calc\(-1 \* var\(--sk-frame-pad-left, 0px\)\)\s+calc\(-1 \* var\(--sk-frame-pad-right, 0px\)\);[^}]*--sk-bar-inset: max\(0px, calc\(\(100% - var\(--sk-room-max\)\) \/ 2\)\);\s*padding-inline: calc\(var\(--sk-frame-pad-left, 0px\) \+ var\(--sk-bar-inset\)\)\s+calc\(var\(--sk-frame-pad-right, 0px\) \+ var\(--sk-bar-inset\)\);/;
    const strip = read("../src/features/mcp-apps/sidekick-shell.css");
    expect(strip).toMatch(
      new RegExp(`\\.sk-rooms__bar \\{[^}]*${bleed.source}`),
    );
    // The tab row bleeds the same way; its tabs and tools keep the rooms' reading width inside the band (ui-8).
    const shell = read("../src/features/work-app/work-shell.css");
    expect(shell).toMatch(
      /\.sk-shell-tabs \{[^}]*margin-inline: calc\(-1 \* var\(--sk-frame-pad-left, 0px\)\)\s+calc\(-1 \* var\(--sk-frame-pad-right, 0px\)\);[^}]*--sk-tabs-inset: max\(0px, calc\(\(100% - var\(--sk-room-max\)\) \/ 2\)\);\s*padding-inline: calc\(var\(--sk-frame-pad-left, 0px\) \+ var\(--sk-tabs-inset\)\)\s+calc\(var\(--sk-frame-pad-right, 0px\) \+ var\(--sk-tabs-inset\)\);/,
    );
    // The frame's side padding is what the bands take back (layout.css).
    const layout = read("../src/features/mcp-apps/ui/layout.css");
    expect(layout).toMatch(/padding-right: var\(--sk-frame-pad-right\);/);
    expect(layout).toMatch(/padding-left: var\(--sk-frame-pad-left\);/);
  });

  it("sticks Kontroll's segmented tabs at the same offset", () => {
    const css = read("../src/features/control-app/control.css");
    expect(css).toMatch(
      /\.sidekick-control \.sk-segmented \{[^}]*position: sticky;[^}]*top: var\(--sk-sticky-top\);/,
    );
  });
});
