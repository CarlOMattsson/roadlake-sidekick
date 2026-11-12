import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Fold } from "@/features/mcp-apps/ui/fold";

import { readStylesheet } from "./helpers/stylesheet";

describe("Fold, the one fold row", () => {
  it("is a button with aria-expanded, the counted text, an optional meta line, and ⌄ last", () => {
    const onToggle = vi.fn();
    render(
      <Fold
        text="Done here (2)"
        meta="Since you opened the agenda"
        open={false}
        onToggle={onToggle}
      />,
    );
    const fold = screen.getByRole("button");
    expect(fold).toHaveClass("sk-fold");
    expect(fold).toHaveAttribute("type", "button");
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(fold.querySelector(".sk-count")).toHaveTextContent("(2)");
    expect(fold.querySelector(".sk-fold-meta")).toHaveTextContent(
      "Since you opened the agenda",
    );
    expect(fold.lastElementChild?.tagName.toLowerCase()).toBe("svg");
    fireEvent.click(fold);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("has no meta element without a meta, reports open, and takes an extra class", () => {
    render(
      <Fold text="Contact ways" open onToggle={vi.fn()} className="extra" />,
    );
    const fold = screen.getByRole("button", { name: "Contact ways" });
    expect(fold).toHaveClass("sk-fold", "extra");
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(fold.querySelector(".sk-fold-meta")).toBeNull();
  });
});

describe("the fold row and the action row in CSS", () => {
  const rowCss = readStylesheet("features/mcp-apps/ui/row.css");
  const room = { room: "sidekick-work" };

  it("a rendered .sk-fold is the section type in ink, a 48 target with no fill or edge, and ⌄ turns up when open", () => {
    render(<Fold text="Done (2)" meta="Since" open onToggle={vi.fn()} />);
    const fold = screen.getByRole("button");

    expect(rowCss.styleOf(fold, room)).toMatchObject({
      "min-height": "var(--sk-row-min)",
      font: "var(--sk-type-section)",
      color: "var(--sk-fg)",
      border: "0",
      background: "none",
    });
    expect(
      rowCss.styleOf(fold.querySelector(".sk-fold-meta") as Element, room),
    ).toMatchObject({ font: "var(--sk-type-meta)", color: "var(--sk-muted)" });
    expect(
      rowCss.styleOf(fold.querySelector("svg") as Element, room).transform,
    ).toBe("rotate(180deg)");
  });

  it("a closed fold's ⌄ does not turn", () => {
    render(<Fold text="Done (2)" open={false} onToggle={vi.fn()} />);

    expect(
      rowCss.styleOf(screen.getByRole("button").querySelector("svg") as Element)
        .transform,
    ).toBeUndefined();
  });

  it(".sk-action-row is the list's tertiary row: 48 high, medium weight, ink, no fill or edge, a glyph in the ring's column", () => {
    render(
      <button type="button" className="sk-action-row">
        <svg aria-hidden="true" />
        Move all
      </button>,
    );
    const action = screen.getByRole("button");

    const style = rowCss.styleOf(action, room);
    expect(style).toMatchObject({
      "min-height": "var(--sk-row-min)",
      color: "var(--sk-fg)",
      border: "0",
      background: "none",
    });
    expect(style.font).toContain("var(--sk-weight-medium)");
    expect(
      rowCss.styleOf(action.querySelector("svg") as Element, room),
    ).toMatchObject({ width: "var(--sk-ring-glyph)", flex: "none" });
  });

  it("the rules of the old folds and action rows are gone from the app sheets", () => {
    const stylesheets = {
      work: readStylesheet("features/work-app/shell/work.css"),
      detail: readStylesheet("features/work-app/tasks/task-detail.css"),
      contacts: readStylesheet("features/work-app/contacts/contacts.css"),
      shopping: readStylesheet("features/shopping-app/shopping.css"),
    };
    const selectors = (sheet: { rules: readonly { selector: string }[] }) =>
      sheet.rules.map((rule) => rule.selector).join("\n");

    expect(selectors(stylesheets.work)).not.toContain(".work-board-fold");
    expect(selectors(stylesheets.shopping)).not.toContain(
      ".shopping-bought-toggle",
    );
    expect(selectors(stylesheets.shopping)).not.toContain(
      ".shopping-purchased > summary",
    );
    expect(selectors(stylesheets.contacts)).not.toContain(
      ".work-contact-ways-value",
    );
    expect(selectors(stylesheets.contacts)).not.toContain(
      ".work-contact-ways > button",
    );
    expect(stylesheets.detail.has(".sidekick-work .work-add-row")).toBe(false);
  });
  it("the open row menu has a panel edge from the secondary button's --sk-border, and --sk-panel-line is gone", () => {
    const tokens = readStylesheet("features/mcp-apps/ui/tokens.css");
    const agenda = readStylesheet("features/work-app/agenda/agenda.css");
    const properties = [...tokens.rules, ...agenda.rules].flatMap((rule) =>
      Object.keys(rule.declarations),
    );
    const values = agenda.rules.flatMap((rule) =>
      Object.values(rule.declarations),
    );

    expect(properties).not.toContain("--sk-panel-line");
    expect(properties).toContain("--sk-border");
    expect(values).toContain("inset 0 0 0 var(--sk-hairline) var(--sk-border)");
  });
});
