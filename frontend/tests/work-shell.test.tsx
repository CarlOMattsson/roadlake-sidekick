import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Segmented } from "@/features/mcp-apps/ui/segmented";
import { TaskProps } from "@/features/work-app/tasks/task-detail-controls";
import { workEn } from "@/features/work-app/shared/labels";
import {
  WorkShell,
  type WorkShellProps,
} from "@/features/work-app/shell/work-shell";
import {
  workShellLabelsEn,
  workShellLabelsFor,
  workShellLabelsSv,
} from "@/features/work-app/shell/work-shell-labels";

import { readSource } from "./helpers/source-files";
import { readStylesheet } from "./helpers/stylesheet";

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

// jsdom applies no CSS, so the rules are read from the stylesheets and resolved against the rendered markup.
const ROOM = { room: "sidekick-work" };
const shellCss = readStylesheet("features/work-app/shell/work-shell.css");
const layoutCss = readStylesheet("features/mcp-apps/ui/layout.css");
const tokensCss = readStylesheet("features/mcp-apps/ui/tokens.css");
const detailCss = readStylesheet("features/work-app/tasks/task-detail.css");

describe("fullscreen clearance above the host reply field", () => {
  it(".sk-shell adds no bottom padding (the frame keeps the foot reserve)", () => {
    render(<WorkShell labels={workShellLabelsEn} {...panels()} />);
    const shell = document.querySelector(".sk-shell") as HTMLElement;

    expect(shellCss.styleOf(shell, ROOM)["padding-block-end"]).toBeUndefined();
    expect(shellCss.styleOf(shell, ROOM)["padding-bottom"]).toBeUndefined();
    // --work-undo-bottom was read by nothing and is gone.
    for (const rule of shellCss.rules) {
      expect(Object.keys(rule.declarations)).not.toContain(
        "--work-undo-bottom",
      );
    }
  });

  it("keeps the foot reserve below the frame content", () => {
    render(<WorkShell labels={workShellLabelsEn} {...panels()} />);
    const body = document.querySelector(".sk-frame__body") as HTMLElement;

    expect(layoutCss.styleOf(body, ROOM)["padding-bottom"]).toBe(
      "calc(var(--sk-frame-pad) + var(--sk-foot-reserve, 6rem))",
    );
  });

  it("defines the foot reserve as the larger of the host inset and 6rem", () => {
    expect(tokensCss.rule(":root")["--sk-foot-reserve"]).toBe(
      "max(var(--host-safe-bottom, 0px), 6rem)",
    );
  });
});

describe("task detail layout at 320 px", () => {
  it("leaves the detail its 16 px page margin, and has no status segments: the status is a property chip", () => {
    render(
      <TaskProps
        hasDue={false}
        busy={false}
        status="todo"
        labels={workEn}
        onDue={vi.fn()}
        onStatus={vi.fn()}
      />,
    );

    // The detail has no frame of its own and adds no side padding: its 16 px side margin is the page's (the
    // fullscreen frame body, layout.css), the same as every other screen.
    expect(detailCss.rule(".sidekick-work .work-task")).toMatchObject({
      padding: "0",
      border: "0",
    });
    expect(
      layoutCss.rule('.sk-frame[data-mode="full"] > .sk-frame__body')[
        "--sk-frame-pad"
      ],
    ).toBe("16px");
    // The status and the due date are property chips, not a radio group.
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    for (const chip of screen.getAllByRole("button")) {
      expect(chip).toHaveClass("sk-chip", "work-prop-chip");
    }
    expect(
      detailCss.rules.map((rule) => rule.selector).join("\n"),
    ).not.toContain("work-task-status");
  });

  it("sizes Markera klar to its text (a compact primary with no rule of its own), and gives each Step the row template's --sk-row-pad above and below inside its --sk-row-min", () => {
    render(
      <TaskProps
        hasDue={false}
        busy={false}
        status="todo"
        labels={workEn}
        onDue={vi.fn()}
        onStatus={vi.fn()}
        done={
          <button type="button" className="sk-btn sk-btn--compact">
            Done
          </button>
        }
      />,
    );
    const family = readStylesheet("features/mcp-apps/ui/family.css");
    const done = screen.getByRole("button", { name: "Done" });

    // The button is the family's compact primary, as wide as its text; the old full-width rule is gone. It is the
    // last control of the property row (task-detail-controls.tsx renders `done` after the chips).
    expect(done.parentElement?.lastElementChild).toBe(done);
    const compact = family.styleOf(done, ROOM);
    expect(compact.width).not.toBe("100%");
    expect(compact["white-space"]).toBe("nowrap");
    // Its one rule of its own only lifts it to the 44 of the chips beside it; its width stays the family's.
    for (const rule of detailCss.rules.filter((rule) =>
      rule.selector.includes("work-task-done"),
    ))
      expect(rule.declarations, rule.selector).toEqual({
        "min-height": "var(--sk-tap)",
      });
    // The air lies inside the label's 48 (no ⋯), and the list rises by --sk-row-air-extra.
    expect(detailCss.has(".sidekick-work .work-steps > li")).toBe(false);
    expect(
      detailCss.rule(".sidekick-work .work-steps :is(label, .work-step-read)"),
    ).toMatchObject({
      "min-height": "var(--sk-row-min)",
      "padding-block": "var(--sk-row-pad)",
    });
    expect(detailCss.rule(".sidekick-work .work-steps").margin).toBe(
      "calc(-1 * var(--sk-row-air-extra)) 0 0",
    );
  });

  it("gives a linked Contact no ⋯ button, only a › that opens it (removal is in the row's own menu)", () => {
    const source = readSource(
      "features/work-app/tasks/task-contacts-section.tsx",
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
  const shellBarCss = readStylesheet("features/mcp-apps/sidekick-shell.css");
  const BLEED =
    "calc(-1 * var(--sk-frame-pad-left, 0px)) calc(-1 * var(--sk-frame-pad-right, 0px))";

  /** The band declarations both stuck rows share: bled to the frame's edges, content kept at the reading width. */
  function expectBand(style: Record<string, string>, inset: string) {
    expect(style["margin-inline"]).toBe(BLEED);
    expect(style[inset]).toBe(
      "max(0px, calc((100% - var(--sk-room-max)) / 2))",
    );
    expect(style["padding-inline"]).toBe(
      `calc(var(--sk-frame-pad-left, 0px) + var(${inset})) calc(var(--sk-frame-pad-right, 0px) + var(${inset}))`,
    );
  }

  it("sticks Work's tab row at the shell's sticky offset, above the list", () => {
    render(<WorkShell labels={workShellLabelsEn} {...panels()} />);
    const tabs = document.querySelector(".sk-shell-tabs") as HTMLElement;

    expect(shellCss.styleOf(tabs, ROOM)).toMatchObject({
      position: "sticky",
      top: "var(--sk-sticky-top)",
      "z-index": "2",
    });
  });

  it("gives the list the offset under the strip and the tab row, whose height is --sk-tabs-h (--sk-sticky-top)", () => {
    render(<WorkShell labels={workShellLabelsEn} {...panels()} />);
    const list = document.querySelector(".sk-shell-list") as HTMLElement;

    const offset = shellBarCss.styleOf(list, ROOM)["--sk-sticky-top"];
    expect(offset).toBe(
      "calc(var(--host-safe-top, 0px) + var(--sk-bar-h, 0px) + var(--sk-tabs-h))",
    );
    // The tab row and its tools use the same height token, so the offset is the row's real height.
    expect(offset).not.toContain("--sk-tap");
    expect(
      readStylesheet("features/work-app/shell/view-tabs.css").rules.map(
        (rule) => rule.declarations.height,
      ),
    ).toContain("var(--sk-tabs-h)");
    expect(shellCss.rules.map((rule) => rule.declarations.height)).toContain(
      "var(--sk-tabs-h)",
    );
    expect(tokensCss.rule(":root")["--sk-tabs-h"]).toBe(
      "min(var(--sk-tap), 56px)",
    );
  });

  it("paints the stuck room strip bar and Work's tab row to the frame's side edges, one band of one width", () => {
    render(<WorkShell labels={workShellLabelsEn} {...panels()} />);
    const tabs = document.querySelector(".sk-shell-tabs") as HTMLElement;

    // The strip and the Back row keep the rooms' reading width inside the band, as the tab row's tabs do.
    expectBand(shellBarCss.rule(".sk-rooms__bar"), "--sk-bar-inset");
    // The tab row bleeds the same way; its tabs and tools keep the rooms' reading width inside the band.
    expectBand(shellCss.styleOf(tabs, ROOM), "--sk-tabs-inset");
    // The frame's side padding is what the bands take back (layout.css).
    const body = document.querySelector(".sk-frame__body") as HTMLElement;
    expect(layoutCss.styleOf(body, ROOM)).toMatchObject({
      "padding-right": "var(--sk-frame-pad-right)",
      "padding-left": "var(--sk-frame-pad-left)",
    });
  });

  it("sticks Kontroll's segmented tabs at the same offset", () => {
    render(
      <Segmented
        label="Kontroll"
        options={[{ value: "a", label: "A" }]}
        value="a"
        onChange={vi.fn()}
      />,
    );
    const group = screen.getByRole("group", { name: "Kontroll" });

    expect(
      readStylesheet("features/control-app/control.css").styleOf(group, {
        room: "sidekick-control",
      }),
    ).toMatchObject({ position: "sticky", top: "var(--sk-sticky-top)" });
  });
});
