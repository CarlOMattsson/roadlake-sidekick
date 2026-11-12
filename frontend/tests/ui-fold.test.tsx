import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { Fold } from "@/features/mcp-apps/ui/fold";

const srcDir = path.resolve(import.meta.dirname, "../src/features");
const read = (rel: string) => readFileSync(path.join(srcDir, rel), "utf8");
const bodyOf = (css: string, selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return (
    new RegExp(`(?:^|[\\s,}])${escaped}\\s*\\{([^}]*)\\}`, "m").exec(
      css,
    )?.[1] ?? ""
  );
};

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
  const rowCss = read("mcp-apps/ui/row.css");

  it(".sk-fold is the section type in ink, a 48 target with no fill or edge, and ⌄ turns up when open", () => {
    const fold = bodyOf(
      rowCss,
      ":is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control)\n  .sk-fold",
    );
    expect(fold).toContain("min-height: var(--sk-row-min);");
    expect(fold).toContain("font: var(--sk-type-section);");
    expect(fold).toContain("color: var(--sk-fg);");
    expect(fold).toContain("border: 0;");
    expect(fold).toContain("background: none;");
    expect(bodyOf(rowCss, ".sk-fold-meta")).toContain(
      "font: var(--sk-type-meta);",
    );
    expect(bodyOf(rowCss, ".sk-fold-meta")).toContain(
      "color: var(--sk-muted);",
    );
    expect(bodyOf(rowCss, '.sk-fold[aria-expanded="true"] > svg')).toContain(
      "transform: rotate(180deg);",
    );
  });

  it(".sk-action-row is the list's tertiary row: 48 high, medium weight, ink, no fill or edge, a glyph in the ring's column", () => {
    const action = bodyOf(
      rowCss,
      ":is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control)\n  .sk-action-row",
    );
    expect(action).toContain("min-height: var(--sk-row-min);");
    expect(action).toContain("var(--sk-weight-medium)");
    expect(action).toContain("color: var(--sk-fg);");
    expect(action).toContain("border: 0;");
    expect(action).toContain("background: none;");
    const glyph = bodyOf(rowCss, ".sk-action-row > svg");
    expect(glyph).toContain("width: var(--sk-ring-glyph);");
    expect(glyph).toContain("flex: none;");
  });

  it("the rules of the old folds and action rows are gone from the app sheets", () => {
    const work = read("work-app/work.css");
    const agenda = read("work-app/agenda.css");
    const detail = read("work-app/task-detail.css");
    const contacts = read("work-app/contacts.css");
    const shopping = read("shopping-app/shopping.css");
    expect(work).not.toMatch(/\.work-board-fold/);
    expect(shopping).not.toMatch(/\.shopping-bought-toggle/);
    expect(shopping).not.toMatch(/\.shopping-purchased\s*>\s*summary/);
    expect(contacts).not.toMatch(/\.work-contact-ways-value/);
    expect(contacts).not.toMatch(/\.work-contact-ways\s*>\s*button/);
    expect(detail).not.toMatch(/^\.sidekick-work \.work-add-row\s*\{/m);
    expect(agenda).not.toMatch(/button\.work-agenda-move-all\s*\{/);
  });

  it("the open row menu has a panel edge from the secondary button's --sk-border, and --sk-panel-line is gone", () => {
    const tokens = read("mcp-apps/ui/tokens.css");
    expect(tokens).not.toMatch(/--sk-panel-line/);
    expect(tokens).toMatch(/--sk-border:/);
    const agenda = read("work-app/agenda.css");
    expect(agenda).not.toMatch(/--sk-panel-line/);
    expect(agenda).toMatch(
      /box-shadow:\s*inset 0 0 0 var\(--sk-hairline\) var\(--sk-border\);/,
    );
  });
});
