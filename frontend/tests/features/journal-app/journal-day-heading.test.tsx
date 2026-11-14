// The day view's heading: the long form where it fits the title row, the short weekday where it would wrap,
// with the long form kept as the heading's name. Layout is faked here (jsdom has none); the real fit is in
// tests/e2e/journal-mcp-app.spec.ts.
import { render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DayHeading } from "@/features/journal-app/day-heading";

const LONG = "Wednesday 4 November";
const SHORT = "Wed 4 November";

/** A title row `room` px wide, and a font where each character is 10 px. */
function layout(room: number) {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(room);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    font: "",
    measureText: (text: string) => ({ width: text.length * 10 }),
  } as unknown as CanvasRenderingContext2D);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DayHeading", () => {
  it("shows the long form where it fits", () => {
    layout(400);
    render(<DayHeading ref={createRef()} long={LONG} short={SHORT} />);
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent(LONG);
    expect(heading).not.toHaveAttribute("aria-label");
  });

  it("shows the short weekday where the long form would wrap, and keeps the long form as its name", () => {
    layout(150);
    const ref = createRef<HTMLHeadingElement>();
    render(<DayHeading ref={ref} long={LONG} short={SHORT} />);
    const heading = screen.getByRole("heading", { level: 2, name: LONG });
    expect(heading).toHaveTextContent(SHORT);
    // The ref is the heading the day view focuses after a move.
    expect(ref.current).toBe(heading);
    expect(heading).toHaveAttribute("tabindex", "-1");
  });

  it("keeps the long form without layout", () => {
    layout(0);
    render(<DayHeading ref={createRef()} long={LONG} short={SHORT} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(LONG);
  });
});
