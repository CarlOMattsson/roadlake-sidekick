// The month calendar of the Journal's list pane (month-rail.tsx): 42 cells in whole weeks, a dot on a day with entries,
// the chosen day or the chosen week filled, ‹ › that step a month, and the month's name in both languages. The calendar
// receives dates only, so nothing here reads journal text. A simulated host, not a proof in the real Claude or Android.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { weekDates } from "@/features/journal-app/dates";
import {
  dayStripLabelsEn,
  dayStripLabelsSv,
} from "@/features/journal-app/day-strip-labels";
import {
  MonthRail,
  type MonthRailProps,
} from "@/features/journal-app/month-rail";
import { transportMock } from "@tests/helpers/journal-app-fixtures";

// Friday 20 November 2026. The November grid runs from Monday 26 October to Sunday 6 December.
const TODAY = "2026-11-20";

function props(overrides: Partial<MonthRailProps> = {}): MonthRailProps {
  return {
    transport: transportMock({
      listEntryDates: vi.fn(() =>
        Promise.resolve(["2026-11-03", "2026-11-18"]),
      ),
    }),
    selected: "2026-11-18",
    today: TODAY,
    labels: dayStripLabelsEn,
    onSelect: vi.fn(),
    ...overrides,
  };
}

function cell(date: string): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>(
    `button[data-date="${date}"]`,
  );
  if (!button) throw new Error(`No cell for ${date}`);
  return button;
}

describe("the month calendar", () => {
  it("draws 42 days in whole weeks from the Monday of the week with the 1st, and names the month", () => {
    render(<MonthRail {...props()} />);

    expect(document.querySelectorAll("button[data-date]")).toHaveLength(42);
    expect(
      document.querySelector("button[data-date]")?.getAttribute("data-date"),
    ).toBe("2026-10-26");
    expect(cell("2026-12-06")).toBeInTheDocument();
    expect(screen.getByText("November 2026")).toBeInTheDocument();
    // Seven weekday names above the grid, Monday first.
    expect(
      Array.from(document.querySelectorAll(".sk-month-weekday")).map(
        (node) => node.textContent,
      ),
    ).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  });

  it("names the month in Swedish with a capital letter", () => {
    render(<MonthRail {...props({ labels: dayStripLabelsSv })} />);

    expect(screen.getByText("November 2026")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Föregående månad" }),
    ).toBeInTheDocument();
    expect(document.querySelector(".sk-month-weekday")).toHaveTextContent(
      "mån",
    );
  });

  it("marks the days with entries, today, the chosen day and the days outside the month", async () => {
    render(<MonthRail {...props()} />);

    await waitFor(() =>
      expect(cell("2026-11-03")).toHaveAttribute("data-has-entries", "true"),
    );
    expect(cell("2026-11-18")).toHaveAttribute("data-has-entries", "true");
    expect(cell("2026-11-04")).not.toHaveAttribute("data-has-entries");
    expect(cell("2026-11-18")).toHaveAttribute("aria-current", "date");
    expect(cell("2026-11-19")).not.toHaveAttribute("aria-current");
    expect(cell("2026-11-20")).toHaveAttribute("data-today", "true");
    expect(cell("2026-10-26")).toHaveAttribute("data-outside", "true");
    expect(cell("2026-11-10")).not.toHaveAttribute("data-outside");
    expect(cell("2026-11-18")).toHaveAccessibleName(
      "Wednesday 18 November, selected, has entries",
    );
  });

  it("lets the day the view has read decide its own dot", async () => {
    render(
      <MonthRail
        {...props({ known: { date: "2026-11-18", hasEntries: false } })}
      />,
    );

    await waitFor(() =>
      expect(cell("2026-11-03")).toHaveAttribute("data-has-entries", "true"),
    );
    expect(cell("2026-11-18")).not.toHaveAttribute("data-has-entries");
  });

  it("opens the day that is pressed, and leaves the days after today alone", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<MonthRail {...props({ onSelect })} />);

    await user.click(cell("2026-11-10"));
    expect(onSelect).toHaveBeenCalledWith("2026-11-10");
    expect(cell("2026-11-21")).toBeDisabled();
    await user.click(cell("2026-11-21"));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("fills the whole week in the week view, and no single day", () => {
    render(
      <MonthRail
        {...props({
          selected: "2026-11-16",
          week: weekDates("2026-11-16"),
        })}
      />,
    );

    const filled = Array.from(
      document.querySelectorAll("button[data-week]"),
    ).map((node) => node.getAttribute("data-date"));
    expect(filled).toEqual(weekDates("2026-11-16"));
    expect(cell("2026-11-16")).toHaveAttribute("data-week", "start");
    expect(cell("2026-11-22")).toHaveAttribute("data-week", "end");
    expect(document.querySelector('[aria-current="date"]')).toBeNull();
  });

  it("draws no dot and no chosen day while a tag is chosen", async () => {
    const transport = transportMock({
      listEntryDates: vi.fn(() => Promise.resolve(["2026-11-03"])),
    });
    render(<MonthRail {...props({ transport, unmarked: true })} />);

    await waitFor(() => expect(transport.listEntryDates).toHaveBeenCalled());
    expect(document.querySelector("[data-has-entries]")).toBeNull();
    expect(document.querySelector('[aria-current="date"]')).toBeNull();
    // A day can still be pressed: it opens that day and leaves the filter.
    expect(cell("2026-11-10")).toBeEnabled();
  });

  it("steps a month with ‹ and ›, reads the dots of the month shown, and cannot step past today's month", async () => {
    const user = userEvent.setup();
    const listEntryDates = vi.fn(() => Promise.resolve([] as string[]));
    render(
      <MonthRail
        {...props({ transport: transportMock({ listEntryDates }) })}
      />,
    );
    const previous = screen.getByRole("button", { name: "Previous month" });
    const next = screen.getByRole("button", { name: "Next month" });
    // Ahead of the newest month there is nothing to show: › says so and does nothing.
    expect(next).toHaveAttribute("aria-disabled", "true");
    await user.click(next);
    expect(screen.getByText("November 2026")).toBeInTheDocument();

    await user.click(previous);
    expect(screen.getByText("October 2026")).toBeInTheDocument();
    expect(document.querySelectorAll("button[data-date]")).toHaveLength(42);
    await waitFor(() =>
      expect(listEntryDates).toHaveBeenLastCalledWith(
        "2026-09-28",
        "2026-11-08",
      ),
    );
    expect(next).not.toHaveAttribute("aria-disabled");
    await user.click(next);
    expect(screen.getByText("November 2026")).toBeInTheDocument();
  });

  it("moves the focus a week with ↑ and ↓ and keeps one tab stop on the chosen day", () => {
    render(<MonthRail {...props()} />);

    expect(cell("2026-11-18")).toHaveAttribute("tabindex", "0");
    expect(cell("2026-11-17")).toHaveAttribute("tabindex", "-1");
    cell("2026-11-18").focus();
    fireEvent.keyDown(cell("2026-11-18"), { key: "ArrowUp" });
    expect(cell("2026-11-11")).toHaveFocus();
    fireEvent.keyDown(cell("2026-11-11"), { key: "ArrowDown" });
    expect(cell("2026-11-18")).toHaveFocus();
    // A week ahead of the 18th is the 25th, after today: the focus stays.
    fireEvent.keyDown(cell("2026-11-18"), { key: "ArrowDown" });
    expect(cell("2026-11-18")).toHaveFocus();
  });

  it("follows a day chosen elsewhere to its month", () => {
    const { rerender } = render(<MonthRail {...props()} />);
    rerender(<MonthRail {...props({ selected: "2026-10-12" })} />);

    expect(screen.getByText("October 2026")).toBeInTheDocument();
    expect(cell("2026-10-12")).toHaveAttribute("aria-current", "date");
  });
});
