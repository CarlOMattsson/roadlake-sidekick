import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Segmented,
  type SegmentedOption,
} from "@/features/mcp-apps/ui/segmented";

const uiDir = path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui");
const workDir = path.resolve(import.meta.dirname, "../src/features/work-app");

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

describe("Segmented styling", () => {
  it("keeps every option at least 44 px high and out of a horizontal scroll", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");

    expect(css).toMatch(
      /\.sk-segmented__option\s*\{[^}]*min-height:\s*2\.75rem/,
    );
    expect(css).toMatch(/\.sk-segmented\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(css).not.toMatch(/overflow-x:\s*(auto|scroll)/);
  });

  it("uses only host tokens with fallbacks, no own colour scheme media query", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");

    expect(css).not.toMatch(/prefers-color-scheme/);
    expect(css).toMatch(/var\(--color-text-primary,\s*light-dark\(/);
  });

  it("shares the row equally with 12 px inside each option, and a 1 px frame with no gap or padding", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");

    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*flex:\s*1 1 0/,
    );
    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*padding:\s*0\.25rem 0\.75rem;/,
    );
    expect(css).toMatch(
      /\.sk-segmented\s*\{[^}]*border:\s*1px solid var\(--sk-border,/,
    );
    expect(css).toMatch(/\.sk-segmented\s*\{[^}]*gap:\s*0;/);
    expect(css).toMatch(/\.sk-segmented\s*\{[^}]*padding:\s*0;/);
    expect(css).toMatch(/\.sk-segmented\s*\{[^}]*background:\s*transparent/);
    // Each option reaches 1 px over the frame, so the pressed contour replaces the frame line where it lies.
    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*margin:\s*-1px;/,
    );
  });

  it("never narrows an option below its longest word, and wraps the row when the options do not fit", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");

    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*min-width:\s*min-content/,
    );
    expect(css).toMatch(/\.sk-segmented\s*\{[^}]*flex-wrap:\s*wrap/);
  });

  it("wraps a label inside its option and never cuts it with an ellipsis, and the option keeps its own border and background", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");

    expect(css).not.toMatch(/text-overflow:\s*ellipsis/);
    expect(css).not.toMatch(/-webkit-line-clamp|line-clamp:/);
    expect(css).toMatch(/\.sk-segmented__label\s*\{[^}]*white-space:\s*normal/);
    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*line-height:\s*1\.2;/,
    );
    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*text-align:\s*center/,
    );
    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*border:\s*0/,
    );
    expect(css).toMatch(
      /\.sk-segmented \.sk-segmented__option\s*\{[^}]*background:\s*transparent/,
    );
  });

  it("fills the pressed option with the toned fill, the text colour and 600, not an inverse fill", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");
    const pressed =
      /\.sk-segmented \.sk-segmented__option\[aria-pressed="true"\]\s*\{([^}]*)\}/.exec(
        css,
      )?.[1];

    expect(pressed, "pressed option rule").toBeDefined();
    expect(pressed).toMatch(
      /background:\s*var\(--sk-selected-bg,\s*light-dark\(/,
    );
    expect(pressed).toMatch(/color:\s*var\(--sk-seg-fg\)/);
    expect(pressed).toMatch(
      /font-weight:\s*var\(--font-weight-semibold,\s*600\)/,
    );
    expect(css).not.toMatch(/--sk-seg-on-/);
  });

  it("marks the pressed option with a 2 px contour in the text colour, and its focus ring is the family's one ring", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");
    const family = readFileSync(path.join(uiDir, "family.css"), "utf8");
    const pressed =
      /\.sk-segmented \.sk-segmented__option\[aria-pressed="true"\]\s*\{([^}]*)\}/.exec(
        css,
      )?.[1];

    expect(pressed, "pressed option rule").toBeDefined();
    expect(pressed).toMatch(
      /box-shadow:\s*inset 0 0 0 var\(--sk-selected-width,\s*2px\)\s*var\(--sk-selected-line,\s*var\(--sk-seg-fg\)\)/,
    );
    expect(pressed).not.toMatch(/--sk-seg-ring/);
    // One focus ring for every control: segmented.css draws none of its own, family.css draws it for all.
    expect(css.replace(/\/\*[\s\S]*?\*\//g, "")).not.toMatch(
      /outline|--sk-seg-ring/,
    );
    expect(family).toMatch(
      /:focus-visible,\s*:is\(\.work-banner, \.journal-banner\):focus\s*\{[^}]*outline:\s*2px solid var\(--sk-ring\);[^}]*outline-offset:\s*2px;/,
    );
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

  it("keeps a label whole in a narrow frame (360 px or less): no line clamp that would hide a line, the option still 44 px high", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");
    const narrow = /@container \(max-width:\s*360px\)\s*\{([\s\S]*?)\n\}/.exec(
      css,
    )?.[1];

    expect(narrow, "narrow frame rule").toBeDefined();
    expect(narrow).not.toMatch(/line-clamp/);
    expect(narrow).not.toMatch(/\.sk-segmented__label/);
    // The cell keeps its 12 px and the frame its 1 px at every width; only the label gets smaller.
    expect(narrow).not.toMatch(/padding/);
    expect(narrow).toMatch(/\.sk-segmented__option--badged\s*\{\s*gap:\s*0;/);
    expect(narrow).not.toMatch(/min-height/);
    expect(css).toMatch(
      /\.sk-segmented__option\s*\{[^}]*min-height:\s*2\.75rem/,
    );
  });

  it("keeps the 1 px frame at 320 px, the label at 0.875rem or more, and no ellipsis", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");
    const narrow = /@container \(max-width:\s*360px\)\s*\{([\s\S]*?)\n\}/.exec(
      css,
    )?.[1];

    expect(narrow, "narrow frame rule").toBeDefined();
    // The frame is not shrunk in the narrow rule: it is 1 px with no gap or padding at every width.
    expect(narrow).not.toMatch(/\.sk-segmented\s*\{/);
    expect(css).toMatch(/\.sk-segmented\s*\{[^}]*gap:\s*0;[^}]*padding:\s*0;/);
    const size = /font-size:\s*([\d.]+)rem;/.exec(narrow ?? "")?.[1];
    expect(size, "narrow label font size").toBeDefined();
    expect(Number(size)).toBeGreaterThanOrEqual(0.875);
    expect(css).not.toMatch(/text-overflow:\s*ellipsis/);
  });

  it("is a nearest-container query, so a Kontroll card (not an .sk-frame app frame) gets the narrow rule too", () => {
    const css = readFileSync(path.join(uiDir, "segmented.css"), "utf8");

    expect(css).not.toMatch(/@container sk-frame \(max-width:\s*360px\)/);
    expect(css).toMatch(/@container \(max-width:\s*360px\)/);
  });
});

describe("Single-column board sections on a phone", () => {
  it("heads each section in the section type and the foreground colour, and folds Klar with the shared fold row", () => {
    const css = readFileSync(path.join(workDir, "work.css"), "utf8");
    const heading =
      /\.work-board\[data-layout="single"\] \.work-column > h3\s*\{([^}]*)\}/.exec(
        css,
      );

    expect(heading?.[1], "single section heading rule").toBeDefined();
    expect(heading?.[1]).toMatch(/font:\s*var\(--sk-type-section\)/);
    expect(heading?.[1]).toMatch(/color:\s*var\(--sk-fg\)/);
    expect(heading?.[1]).not.toMatch(/color:\s*var\(--sk-muted\)/);
    // The own fold rule is gone: "Klar (n)" is the shared .sk-fold, in the section type and ink (row.css).
    expect(css).not.toMatch(/\.work-board-fold/);
    const fold = readFileSync(path.join(uiDir, "row.css"), "utf8");
    const rule = /\.sk-fold\s*\{([^}]*)\}/.exec(fold)?.[1] ?? "";
    expect(rule).toMatch(/font:\s*var\(--sk-type-section\)/);
    expect(rule).toMatch(/color:\s*var\(--sk-fg\)/);
  });
});
