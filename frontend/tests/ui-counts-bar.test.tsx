import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CountsBar,
  type CountsSegment,
} from "@/features/mcp-apps/ui/counts-bar";

const uiDir = path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui");

// The fourth segment has no tone (CountsTone has no "success"): it is drawn neutral by CSS and carries no data-tone.
const segmentsSv: CountsSegment[] = [
  { key: "todo", label: "Att göra", count: 3, tone: "neutral" },
  { key: "in_progress", label: "Pågår", count: 1, tone: "info" },
  { key: "blocked", label: "Blockerad", count: 0, tone: "warning" },
  { key: "completed", label: "Klar", count: 4 },
];

const segmentsEn: CountsSegment[] = [
  { key: "todo", label: "To do", count: 3, tone: "neutral" },
  { key: "in_progress", label: "In progress", count: 1, tone: "info" },
  { key: "blocked", label: "Blocked", count: 0, tone: "warning" },
  { key: "completed", label: "Done", count: 4 },
];

describe.each([
  {
    name: "sv",
    groupLabel: "Uppgifter per status",
    segments: segmentsSv,
    labels: ["Att göra", "Pågår", "Blockerad", "Klar"],
  },
  {
    name: "en",
    groupLabel: "Tasks by status",
    segments: segmentsEn,
    labels: ["To do", "In progress", "Blocked", "Done"],
  },
])("CountsBar ($name)", ({ groupLabel, segments, labels }) => {
  it("names every status and its count in text, in order", () => {
    render(<CountsBar label={groupLabel} segments={segments} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(
      items.map((item) => item.querySelector("span")?.textContent),
    ).toEqual(labels);
    expect(items.map((item) => item.lastElementChild?.textContent)).toEqual([
      "3",
      "1",
      "0",
      "4",
    ]);
    labels.forEach((label, index) => {
      expect(within(items[index]!).getByText(label)).toBeInTheDocument();
    });
  });

  it("is a named group, and the bar is hidden from assistive technology", () => {
    const { container } = render(
      <CountsBar label={groupLabel} segments={segments} />,
    );

    expect(screen.getByRole("group", { name: groupLabel })).toBeInTheDocument();
    const bar = container.querySelector(".sk-counts-bar__bar");
    expect(bar).toHaveAttribute("aria-hidden", "true");
  });

  it("draws one bar segment per non-zero count, sized in proportion", () => {
    const { container } = render(
      <CountsBar label={groupLabel} segments={segments} />,
    );

    const barSegments = Array.from(
      container.querySelectorAll<HTMLElement>(".sk-counts-bar__segment"),
    );
    expect(barSegments.map((segment) => segment.style.flexGrow)).toEqual([
      "3",
      "1",
      "4",
    ]);
    expect(
      barSegments.map((segment) => segment.getAttribute("data-tone")),
    ).toEqual(["neutral", "info", null]);
  });

  it("gives a segment without a tone no data-tone, on its bar segment and its legend item", () => {
    const { container } = render(
      <CountsBar label={groupLabel} segments={segments} />,
    );

    const barSegments = container.querySelectorAll(".sk-counts-bar__segment");
    expect(barSegments[2]).not.toHaveAttribute("data-tone");
    const items = screen.getAllByRole("listitem");
    expect(items[3]).not.toHaveAttribute("data-tone");
    // The toned segments keep theirs.
    expect(items[0]).toHaveAttribute("data-tone", "neutral");
  });

  it("draws the bar when one segment has a count, whatever its tone", () => {
    const { container } = render(
      <CountsBar
        label={groupLabel}
        segments={[{ key: "only", label: labels[0]!, count: 2 }]}
      />,
    );

    expect(container.querySelector(".sk-counts-bar__bar")).not.toBeNull();
    const barSegments = container.querySelectorAll<HTMLElement>(
      ".sk-counts-bar__segment",
    );
    expect(barSegments).toHaveLength(1);
    expect(barSegments[0]?.style.flexGrow).toBe("2");
  });

  it("draws no bar when every count is zero, but still names the zeros", () => {
    const { container } = render(
      <CountsBar
        label={groupLabel}
        segments={segments.map((segment) => ({ ...segment, count: 0 }))}
      />,
    );

    expect(container.querySelector(".sk-counts-bar__bar")).toBeNull();
    expect(container.querySelectorAll(".sk-counts-bar__segment")).toHaveLength(
      0,
    );
    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.lastElementChild?.textContent)).toEqual([
      "0",
      "0",
      "0",
      "0",
    ]);
  });

  it("draws no bar for an empty segment list", () => {
    const { container } = render(
      <CountsBar label={groupLabel} segments={[]} />,
    );

    expect(container.querySelector(".sk-counts-bar__bar")).toBeNull();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("treats negative, NaN and infinite counts as zero and floors fractions", () => {
    const { container } = render(
      <CountsBar
        label={groupLabel}
        segments={[
          { key: "a", label: labels[0]!, count: -2 },
          { key: "b", label: labels[1]!, count: Number.NaN },
          { key: "c", label: labels[2]!, count: Number.POSITIVE_INFINITY },
          { key: "d", label: labels[3]!, count: 2.7 },
        ]}
      />,
    );

    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.lastElementChild?.textContent)).toEqual([
      "0",
      "0",
      "0",
      "2",
    ]);
    const barSegments = container.querySelectorAll<HTMLElement>(
      ".sk-counts-bar__segment",
    );
    expect(barSegments).toHaveLength(1);
    expect(barSegments[0]?.style.flexGrow).toBe("2");
  });

  it("has no buttons or other controls, so nothing can be focused", () => {
    render(<CountsBar label={groupLabel} segments={segments} />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(
      screen
        .getByRole("group", { name: groupLabel })
        .querySelectorAll("[tabindex]"),
    ).toHaveLength(0);
  });
});

describe("CountsBar styling", () => {
  it("wraps the legend instead of scrolling, so four segments fit on 320 px", () => {
    const css = readFileSync(path.join(uiDir, "counts-bar.css"), "utf8");

    expect(css).toMatch(/\.sk-counts-bar__legend\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(css).not.toMatch(/white-space:\s*nowrap/);
    expect(css).not.toMatch(/overflow-x:\s*(auto|scroll)/);
  });

  it("uses only host tokens with fallbacks, no own colour scheme media query", () => {
    const css = readFileSync(path.join(uiDir, "counts-bar.css"), "utf8");

    expect(css).not.toMatch(/prefers-color-scheme/);
    expect(css).toMatch(/var\(--color-text-primary,\s*light-dark\(/);
    // One colour, one meaning: "Att göra" is a mix of ink and page, "Pågår" the ink, and "Blockerad" a hatch
    // (not the overdue red: red means Försenad). Neither role names blue or orange.
    expect(css).toMatch(
      /--sk-cb-neutral:\s*color-mix\(in srgb,\s*var\(--sk-fg\)\s*\d+%,\s*var\(--sk-bg\)\)/,
    );
    expect(css).toMatch(/--sk-cb-info:\s*var\(--sk-fg\)/);
    expect(css).toMatch(
      /--sk-cb-hatch:\s*repeating-linear-gradient\([^;]*var\(--sk-fg\)[^;]*var\(--sk-surface\)/,
    );
    expect(css).not.toMatch(/--sk-cb-warning/);
    expect(css).not.toMatch(/--sk-overdue-fg/);
    const blocked =
      /\.sk-counts-bar__item\[data-tone="warning"\]::before\s*\{([^}]*)\}/.exec(
        css,
      );
    expect(blocked?.[1]).toContain("background: var(--sk-cb-hatch);");
    expect(blocked?.[1]).toContain("box-shadow: inset 0 0 0 1px var(--sk-fg);");
    expect(css).not.toMatch(/--color-text-info|--color-text-warning/);
  });

  it("draws the legend swatch as its segment: 12 wide, as high as the bar, a 2 px radius", () => {
    const css = readFileSync(path.join(uiDir, "counts-bar.css"), "utf8");
    const swatch = /\.sk-counts-bar__item::before\s*\{([^}]*)\}/.exec(css)?.[1];
    expect(swatch).toContain("width: 0.75rem;");
    expect(swatch).toContain("height: 0.5rem;");
    expect(swatch).toContain("border-radius: 2px;");
    expect(swatch).not.toContain("border-radius: 50%;");
    const track = /\.sk-counts-bar__bar\s*\{([^}]*)\}/.exec(css)?.[1];
    expect(track).toContain("height: 0.5rem;");
    expect(track).toContain("border-radius: 2px;");
  });

  it("has no motion, so no reduced-motion variant is needed", () => {
    const css = readFileSync(path.join(uiDir, "counts-bar.css"), "utf8");

    expect(css).not.toMatch(/transition|animation/);
  });
});
