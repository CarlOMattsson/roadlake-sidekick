import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Segmented,
  type SegmentedOption,
} from "@/features/mcp-apps/ui/segmented";

import { Fold } from "@/features/mcp-apps/ui/fold";

import { readStylesheet } from "./helpers/stylesheet";

const optionsSv: SegmentedOption<string>[] = [
  { value: "agenda", label: "Agenda" },
  { value: "board", label: "Board" },
  { value: "hierarki", label: "Hierarki" },
  { value: "kontakter", label: "Kontakter" },
];

const optionsEn: SegmentedOption<string>[] = [
  { value: "agenda", label: "Agenda" },
  { value: "board", label: "Board" },
  { value: "hierarchy", label: "Hierarchy" },
  { value: "contacts", label: "Contacts" },
];

describe.each([
  {
    name: "sv",
    groupLabel: "Vyer",
    options: optionsSv,
    labels: ["Agenda", "Board", "Hierarki", "Kontakter"],
  },
  {
    name: "en",
    groupLabel: "Views",
    options: optionsEn,
    labels: ["Agenda", "Board", "Hierarchy", "Contacts"],
  },
])("Segmented ($name)", ({ groupLabel, options, labels }) => {
  it("shows every option as a visible button with its label, and no menu", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", { name: groupLabel })).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(labels);
    buttons.forEach((button) => {
      expect(button).toHaveAttribute("type", "button");
    });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("marks only the value as pressed with aria-pressed", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="board"
        onChange={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveAttribute("aria-pressed", "false");
    expect(buttons[1]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[2]).toHaveAttribute("aria-pressed", "false");
    expect(buttons[3]).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange with the value when an unpressed option is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: labels[1] }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("board");
  });

  it("does not call onChange when the pressed option is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: labels[0] }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("selects with Enter and Space on the focused option", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    screen.getByRole("button", { name: labels[2] }).focus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(options[2]?.value);

    screen.getByRole("button", { name: labels[3] }).focus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenLastCalledWith(options[3]?.value);
  });

  it("moves focus with arrow keys without changing the selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
      />,
    );

    const first = screen.getByRole("button", { name: labels[0] });
    const second = screen.getByRole("button", { name: labels[1] });
    first.focus();

    await user.keyboard("{ArrowRight}");
    expect(second).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: labels[2] })).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(second).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(first).toHaveFocus();

    expect(onChange).not.toHaveBeenCalled();
    expect(first).toHaveAttribute("aria-pressed", "true");
  });

  it("wraps focus at both ends and jumps with Home and End", async () => {
    const user = userEvent.setup();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={vi.fn()}
      />,
    );

    const first = screen.getByRole("button", { name: labels[0] });
    const last = screen.getByRole("button", { name: labels[3] });
    first.focus();

    await user.keyboard("{ArrowLeft}");
    expect(last).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(first).toHaveFocus();
    await user.keyboard("{End}");
    expect(last).toHaveFocus();
    await user.keyboard("{Home}");
    expect(first).toHaveFocus();
  });

  it("keeps only the pressed option in the Tab order", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value={options[2]?.value ?? null}
        onChange={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.tabIndex)).toEqual([-1, -1, 0, -1]);
  });

  it("makes the first option the Tab stop when nothing is pressed", () => {
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value={null}
        onChange={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    expect(
      buttons.every(
        (button) => button.getAttribute("aria-pressed") === "false",
      ),
    ).toBe(true);
    expect(buttons.map((button) => button.tabIndex)).toEqual([0, -1, -1, -1]);
  });

  it("disables every option while disabled, so clicks do nothing", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label={groupLabel}
        options={options}
        value="agenda"
        onChange={onChange}
        disabled
      />,
    );

    const buttons = screen.getAllByRole("button");
    buttons.forEach((button) => {
      expect(button).toBeDisabled();
    });

    await user.click(screen.getByRole("button", { name: labels[1] }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

const NARROW = "@container (max-width: 360px)";

describe("Segmented styling", () => {
  const sheet = readStylesheet("features/mcp-apps/ui/segmented.css");
  const family = readStylesheet("features/mcp-apps/ui/family.css");

  /** A rendered row with one pressed option, one plain and one with a badge. */
  function renderRow() {
    render(
      <Segmented
        label="Vyer"
        options={[
          { value: "a", label: "Agenda" },
          { value: "b", label: "Board" },
          { value: "c", label: "Klara", badge: "3" },
        ]}
        value="a"
        onChange={vi.fn()}
      />,
    );
    return {
      group: screen.getByRole("group", { name: "Vyer" }),
      pressed: screen.getByRole("button", { name: "Agenda" }),
      plain: screen.getByRole("button", { name: "Board" }),
      badged: screen.getByRole("button", { name: /Klara/ }),
    };
  }

  it("keeps every option at least 44 px high, wrapped onto more rows rather than scrolled", () => {
    const { group, plain } = renderRow();

    expect(sheet.styleOf(plain)["min-height"]).toBe("2.75rem");
    expect(sheet.styleOf(group)["flex-wrap"]).toBe("wrap");
    expect(
      sheet.rules.map((rule) => rule.declarations["overflow-x"]),
    ).not.toContain("auto");
  });

  it("uses host tokens with fallbacks and no colour scheme query of its own", () => {
    const { group } = renderRow();

    expect(sheet.rules.map((rule) => rule.conditions.join(" "))).not.toContain(
      "@media (prefers-color-scheme: dark)",
    );
    expect(sheet.styleOf(group)["--sk-seg-fg"]).toMatch(
      /^var\(--color-text-primary, light-dark\(/,
    );
  });

  it("shares the row equally with 12 px inside each option, and a 1 px frame with no gap or padding", () => {
    const { group, plain } = renderRow();

    expect(sheet.styleOf(plain)).toMatchObject({
      padding: "0.25rem 0.75rem",
      // Each option reaches 1 px over the frame, so the pressed contour replaces the frame line where it lies.
      margin: "-1px",
      "min-width": "min-content",
    });
    expect(sheet.styleOf(group)).toMatchObject({
      gap: "0",
      padding: "0",
      background: "transparent",
    });
    expect(sheet.styleOf(group).border).toMatch(
      /^1px solid var\(--sk-border, /,
    );
  });

  it("wraps a label inside its option and never cuts it with an ellipsis", () => {
    const { plain } = renderRow();
    const label = plain.querySelector(".sk-segmented__label") as HTMLElement;

    expect(sheet.styleOf(label)["white-space"]).toBe("normal");
    expect(sheet.styleOf(plain)).toMatchObject({
      "line-height": "1.2",
      "text-align": "center",
      border: "0",
      background: "transparent",
    });
    for (const rule of sheet.rules) {
      expect(rule.declarations["text-overflow"], rule.selector).toBeUndefined();
      expect(rule.declarations["line-clamp"], rule.selector).toBeUndefined();
      expect(
        rule.declarations["-webkit-line-clamp"],
        rule.selector,
      ).toBeUndefined();
    }
  });

  it("fills the pressed option with the toned fill, the text colour and 600, and marks it with a 2 px contour", () => {
    const { pressed, plain } = renderRow();
    const style = sheet.styleOf(pressed);

    expect(style.background).toMatch(/^var\(--sk-selected-bg, light-dark\(/);
    expect(style.color).toBe("var(--sk-seg-fg)");
    expect(style["font-weight"]).toBe("var(--font-weight-semibold, 600)");
    expect(style["box-shadow"]).toBe(
      "inset 0 0 0 var(--sk-selected-width, 2px) var(--sk-selected-line, var(--sk-seg-fg))",
    );
    // The option that is not pressed gets none of it.
    expect(sheet.styleOf(plain)["box-shadow"]).toBeUndefined();
    expect(sheet.styleOf(plain).color).toBe("var(--sk-seg-muted)");
  });

  it("draws no focus ring of its own: the family's one ring covers every control", () => {
    for (const rule of sheet.rules) {
      expect(rule.declarations.outline, rule.selector).toBeUndefined();
    }
    const ring = family.rule(
      ":focus-visible, :is(.work-banner, .journal-banner):focus",
    );
    expect(ring.outline).toBe("2px solid var(--sk-ring)");
    expect(ring["outline-offset"]).toBe("2px");
  });

  it("wraps a plain label in the label span, so the wrapping applies without a badge", () => {
    render(
      <Segmented
        label="Vyer"
        options={optionsSv}
        value="agenda"
        onChange={vi.fn()}
      />,
    );

    const agenda = screen.getByRole("button", { name: "Agenda" });
    expect(agenda.querySelector(".sk-segmented__label")?.textContent).toBe(
      "Agenda",
    );
  });

  it("in a narrow container only the label gets smaller: the cell keeps its padding, frame and 44 px height", () => {
    const { group, plain, badged } = renderRow();
    const narrowRules = sheet.rules.filter((rule) =>
      rule.conditions.includes(NARROW),
    );

    // A nearest-container query (no name), so a Kontroll card that is not an .sk-frame app frame gets it too.
    expect(narrowRules.length).toBeGreaterThan(0);
    const narrow = sheet.styleOf(plain, { conditions: [NARROW] });
    const size = /^([\d.]+)rem$/.exec(narrow["font-size"] ?? "")?.[1];
    expect(Number(size)).toBeGreaterThanOrEqual(0.875);
    expect(narrow.padding).toBeUndefined();
    expect(narrow["min-height"]).toBeUndefined();
    expect(sheet.styleOf(group, { conditions: [NARROW] })).toEqual({});
    expect(sheet.styleOf(badged, { conditions: [NARROW] }).gap).toBe("0");
    const label = plain.querySelector(".sk-segmented__label") as HTMLElement;
    expect(sheet.styleOf(label, { conditions: [NARROW] })).toEqual({});
  });
});

describe("Single-column board sections on a phone", () => {
  it("heads each section in the section type and the foreground colour, and folds Klar with the shared fold row", () => {
    const work = readStylesheet("features/work-app/shell/work.css");
    const heading = work.rule(
      '.sidekick-work .work-board[data-layout="single"] .work-column > h3',
    );

    expect(heading.font).toBe("var(--sk-type-section)");
    expect(heading.color).toBe("var(--sk-fg)");
    // "Klar (n)" is the shared .sk-fold, in the section type and ink (row.css), not a rule of the board's own.
    expect(work.has(".work-board-fold")).toBe(false);
    render(<Fold text="Klar (2)" open={false} onToggle={vi.fn()} />);
    const fold = readStylesheet("features/mcp-apps/ui/row.css").styleOf(
      screen.getByRole("button"),
      { room: "sidekick-work" },
    );
    expect(fold.font).toBe("var(--sk-type-section)");
    expect(fold.color).toBe("var(--sk-fg)");
  });
});
