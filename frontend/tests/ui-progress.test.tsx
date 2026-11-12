import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Progress } from "@/features/mcp-apps/ui/progress";

const uiDir = path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui");

describe.each([
  { done: 2, total: 5, text: "2/5", width: "40%" },
  { done: 0, total: 5, text: "0/5", width: "0%" },
  { done: 5, total: 5, text: "5/5", width: "100%" },
  { done: 0, total: 0, text: "0/0", width: null },
])("Progress ($done/$total)", ({ done, total, text, width }) => {
  it("always shows the count as text", () => {
    const { container } = render(<Progress done={done} total={total} />);

    expect(container.querySelector(".sk-progress__text")).toHaveTextContent(
      text,
    );
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("draws a bar only when there is a total, and hides it from assistive technology", () => {
    const { container } = render(<Progress done={done} total={total} />);

    const track = container.querySelector(".sk-progress__track");
    if (width === null) {
      expect(track).toBeNull();
      return;
    }
    expect(track).not.toBeNull();
    expect(track).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".sk-progress__fill")).toHaveStyle({
      width,
    });
  });
});

describe("Progress bounds", () => {
  it("clamps done to the total so the bar never passes the track", () => {
    const { container } = render(<Progress done={9} total={4} />);

    expect(screen.getByText("4/4")).toBeInTheDocument();
    expect(container.querySelector(".sk-progress__fill")).toHaveStyle({
      width: "100%",
    });
  });

  it("treats negative and non-finite counts as zero", () => {
    const { container } = render(<Progress done={-1} total={Number.NaN} />);

    expect(screen.getByText("0/0")).toBeInTheDocument();
    expect(container.querySelector(".sk-progress__track")).toBeNull();
  });

  it("floors fractional counts", () => {
    render(<Progress done={2.7} total={5.2} />);

    expect(screen.getByText("2/5")).toBeInTheDocument();
  });
});

describe("Progress styling", () => {
  it("uses host tokens with fallbacks and no fixed colour-scheme media query", () => {
    const css = readFileSync(path.join(uiDir, "progress.css"), "utf8");

    expect(css).not.toMatch(/prefers-color-scheme/);
    expect(css).toMatch(/var\(--color-text-secondary,\s*light-dark\(/);
    expect(css).toMatch(/var\(--color-text-info,\s*light-dark\(/);
  });
});
