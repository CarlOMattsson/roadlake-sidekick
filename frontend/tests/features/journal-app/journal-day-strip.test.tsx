import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  DayStrip,
  stripDays,
  weekRange,
  type DayStripProps,
} from "@/features/journal-app/day-strip";
import { shiftDate } from "@/features/journal-app/dates";
import {
  dayStripLabelsEn,
  dayStripLabelsSv,
} from "@/features/journal-app/day-strip-labels";

// 2026-10-25 is a Sunday; the strip shows the seven days that end on today, 19-25 Oct, so 21 Oct is in them.
const TODAY = "2026-10-25";
const SELECTED = "2026-10-21";
const WEEK = [
  "2026-10-19",
  "2026-10-20",
  "2026-10-21",
  "2026-10-22",
  "2026-10-23",
  "2026-10-24",
  "2026-10-25",
];

function props(overrides: Partial<DayStripProps> = {}): DayStripProps {
  return {
    selected: SELECTED,
    today: TODAY,
    daysWithEntries: ["2026-10-20", "2026-10-23"],
    labels: dayStripLabelsEn,
    onSelect: vi.fn(),
    ...overrides,
  };
}

function dayButton(date: string): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>(
    `button[data-date="${date}"]`,
  );
  if (!button) throw new Error(`No day button for ${date}`);
  return button;
}

/** A single touch event on the strip, with one touch at (x, y), as the browser reports it. */
function touch(
  target: HTMLElement,
  type: "touchStart" | "touchEnd",
  x: number,
  y: number,
) {
  const event = createEvent[type](target);
  Object.defineProperty(
    event,
    type === "touchStart" ? "touches" : "changedTouches",
    { value: [{ clientX: x, clientY: y }] },
  );
  fireEvent(target, event);
}

function swipe(
  target: HTMLElement,
  from: [number, number],
  to: [number, number],
) {
  touch(target, "touchStart", from[0], from[1]);
  touch(target, "touchEnd", to[0], to[1]);
}

/** Seven dates, oldest first, that end on `end`. */
function sevenEndingOn(end: string): string[] {
  return Array.from({ length: 7 }, (_, index) => shiftDate(end, index - 6));
}

describe("stripDays", () => {
  it("returns the seven days that end on today while the selected day is among them", () => {
    expect(stripDays(SELECTED, TODAY)).toEqual(WEEK);
    expect(stripDays(TODAY, TODAY)).toEqual(WEEK);
    expect(stripDays("2026-10-19", TODAY)).toEqual(WEEK);
  });

  it("never shows a day after today: on a Wednesday the strip runs Thursday to Wednesday", () => {
    // 2026-11-04 is a Wednesday.
    expect(stripDays("2026-11-03", "2026-11-04")).toEqual(
      sevenEndingOn("2026-11-04"),
    );
    expect(stripDays("2026-11-03", "2026-11-04")[0]).toBe("2026-10-29");
  });

  it("pages back from today in whole weeks, so the selected day is always shown", () => {
    expect(stripDays("2026-10-18", TODAY)).toEqual(sevenEndingOn("2026-10-18"));
    expect(stripDays("2026-10-12", TODAY)).toEqual(sevenEndingOn("2026-10-18"));
    expect(stripDays("2026-10-11", TODAY)).toEqual(sevenEndingOn("2026-10-11"));
  });

  it("crosses a year boundary", () => {
    expect(stripDays("2026-12-30", "2027-01-02")).toEqual([
      "2026-12-27",
      "2026-12-28",
      "2026-12-29",
      "2026-12-30",
      "2026-12-31",
      "2027-01-01",
      "2027-01-02",
    ]);
  });

  it("shows the seven days that end on a selected day after today", () => {
    expect(stripDays("2026-10-28", TODAY)).toEqual(sevenEndingOn("2026-10-28"));
  });

  it("returns nothing for a malformed date", () => {
    expect(stripDays("2026-10-2", TODAY)).toEqual([]);
    expect(stripDays("not a date", TODAY)).toEqual([]);
  });
});

describe("DayStrip rendering", () => {
  it("shows the seven days of the week in order, as the items of one list", () => {
    render(<DayStrip {...props()} />);
    const shown = Array.from(
      document.querySelectorAll<HTMLButtonElement>("button[data-date]"),
    ).map((button) => button.dataset.date);
    expect(shown).toEqual(WEEK);
    // One week list of seven items; no row or line wrapper in the markup.
    expect(document.querySelectorAll("ol.sk-day-strip-week > li")).toHaveLength(
      7,
    );
    expect(document.querySelector(".sk-day-strip-row")).toBeNull();
    expect(document.querySelector(".sk-day-strip-line")).toBeNull();
  });

  it("marks only the days with entries, with a dot and an accessible name", () => {
    render(<DayStrip {...props()} />);
    for (const date of WEEK) {
      const button = dayButton(date);
      const marked = date === "2026-10-20" || date === "2026-10-23";
      if (marked) {
        expect(button).toHaveAttribute("data-has-entries", "true");
        expect(button).toHaveAccessibleName(/has entries$/);
        // The dot sits in the marker row, centred under the number.
        const dot = button.querySelector(".sk-day-strip-dot");
        expect(dot).not.toBeNull();
        expect(dot?.parentElement).toHaveClass("sk-day-strip-marker");
        expect(dot?.parentElement?.previousElementSibling).toHaveClass(
          "sk-day-strip-number",
        );
      } else {
        expect(button).not.toHaveAttribute("data-has-entries");
        expect(button).not.toHaveAccessibleName(/has entries$/);
        expect(button.querySelector(".sk-day-strip-dot")).toBeNull();
      }
    }
    expect(
      screen.getAllByRole("button", { name: /has entries$/ }),
    ).toHaveLength(2);
  });

  it("ignores entry days that are outside the shown week", () => {
    render(<DayStrip {...props({ daysWithEntries: ["2026-09-30"] })} />);
    expect(document.querySelectorAll("[data-has-entries]")).toHaveLength(0);
  });

  it("shows the weekday and the day number on each day button", () => {
    render(<DayStrip {...props()} />);
    // 2026-10-21 is a Wednesday and 2026-10-20 a Tuesday (English labels in props()).
    expect(dayButton(SELECTED).textContent).toBe("Wed 21");
    expect(dayButton("2026-10-20").textContent).toBe("Tue 20");
  });

  it("says Today where the weekday is, above today's number, and nowhere else", () => {
    render(<DayStrip {...props()} />);
    expect(dayButton(TODAY).textContent).toBe("Today 25");
    const word = dayButton(TODAY).querySelector(".sk-day-strip-today");
    expect(word?.textContent).toBe("Today");
    // The word is the weekday row: the weekday span, and the number comes right after it.
    expect(word).toHaveClass("sk-day-strip-weekday");
    expect(word?.nextElementSibling).toHaveClass("sk-day-strip-number");
    expect(document.querySelectorAll(".sk-day-strip-today")).toHaveLength(1);
    expect(dayButton(TODAY)).toHaveAccessibleName("Today 25 October, Sunday");
  });

  it("says Idag where the weekday is, in Swedish", () => {
    render(<DayStrip {...props({ labels: dayStripLabelsSv })} />);
    expect(dayButton(TODAY).textContent).toBe("Idag 25");
    expect(
      dayButton(TODAY).querySelector(".sk-day-strip-today")?.textContent,
    ).toBe("Idag");
    expect(dayButton(TODAY)).toHaveAccessibleName("Idag 25 oktober, söndag");
  });

  it("puts the title, ⋯ and the week row ('‹ range ›' and then 'Idag') in the head, in that order", () => {
    render(
      <DayStrip
        {...props({
          heading: <h2>Onsdag 21 oktober</h2>,
          actions: <button type="button">Idag</button>,
          more: <button type="button">Mer</button>,
        })}
      />,
    );
    const head = document.querySelector<HTMLElement>(".sk-day-strip-head");
    expect(head).not.toBeNull();
    // One form at every width, so the head carries no data-today-button.
    expect(head).not.toHaveAttribute("data-today-button");
    expect(
      Array.from(
        head?.children ?? [],
        (child) => child.className || child.tagName,
      ),
    ).toEqual([
      "sk-day-strip-title",
      "sk-day-strip-tools",
      "sk-day-strip-weekrow",
    ]);
    // The title holds the heading only; the week's range is in the week row.
    const title = head?.querySelector<HTMLElement>(".sk-day-strip-title");
    expect(Array.from(title?.children ?? [], (child) => child.tagName)).toEqual(
      ["H2"],
    );
    expect(title?.querySelector("h2")).toHaveTextContent("Onsdag 21 oktober");
    expect(title?.querySelector("p.journal-day-range")).toBeNull();
    // The tools hold ⋯ only; the arrows and Idag are in the week row.
    const tools = head?.querySelector<HTMLElement>(".sk-day-strip-tools");
    expect(
      Array.from(tools?.querySelectorAll("button") ?? [], (b) => b.textContent),
    ).toEqual(["Mer"]);
    const weekRow = head?.querySelector<HTMLElement>(".sk-day-strip-weekrow");
    expect(
      Array.from(
        weekRow?.children ?? [],
        (child) =>
          child.getAttribute("aria-label") ||
          child.className ||
          child.textContent,
      ),
    ).toEqual(["Previous week", "journal-day-range", "Next week", "Idag"]);
  });

  it("puts '‹ range ›' in the week row, with no aria-description on the strip", () => {
    render(
      <DayStrip
        {...props({
          heading: <h2>Onsdag 21 oktober</h2>,
        })}
      />,
    );
    const head = document.querySelector<HTMLElement>(".sk-day-strip-head");
    expect(head).not.toHaveAttribute("data-today-button");
    const weekRow = head?.querySelector<HTMLElement>(".sk-day-strip-weekrow");
    expect(weekRow).not.toBeNull();
    expect(weekRow?.parentElement).toBe(head);
    // Order: ‹, the range paragraph, ›; no Idag when the week has today.
    const children = Array.from(weekRow?.children ?? []);
    expect(children).toHaveLength(3);
    expect(children[0]).toHaveAccessibleName("Previous week");
    expect(children[0]).toHaveClass("sk-iconbtn", "sk-day-strip-arrow");
    expect(children[1]?.tagName).toBe("P");
    expect(children[1]).toHaveClass("journal-day-range");
    expect(children[1]).toHaveTextContent(weekRange(WEEK, "en-GB"));
    expect(children[2]).toHaveAccessibleName("Next week");
    expect(children[2]).toHaveClass("sk-iconbtn", "sk-day-strip-arrow");
    expect(document.querySelector(".sk-day-strip-range")).toBeNull();
    expect(document.querySelector(".sk-day-strip-pair")).toBeNull();
    for (const name of ["Previous week", "Next week"]) {
      const arrow = screen.getByRole("button", { name });
      expect(arrow.textContent).toBe("");
      expect(arrow.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    }
    // The strip follows the head directly. Its name is the group label; the range is read in the week row.
    const strip = screen.getByRole("group", { name: "Week" });
    expect(head?.nextElementSibling).toBe(strip);
    expect(strip).toHaveClass("sk-day-strip");
    expect(strip).toHaveAttribute("aria-label", "Week");
    expect(strip).not.toHaveAttribute("aria-description");
    expect(document.querySelector("p.journal-day-range")).toHaveTextContent(
      weekRange(WEEK, "en-GB"),
    );
  });

  it("names the week in the week row in Swedish too", () => {
    render(
      <DayStrip
        {...props({
          labels: dayStripLabelsSv,
        })}
      />,
    );
    const strip = screen.getByRole("group", { name: "Veckan" });
    expect(strip).not.toHaveAttribute("aria-description");
    expect(document.querySelector("p.journal-day-range")).toHaveTextContent(
      weekRange(WEEK, "sv-SE"),
    );
  });

  it("shows no title row action when none is given: the arrows row keeps the arrows alone", () => {
    render(<DayStrip {...props()} />);
    const tools = document.querySelector(".sk-day-strip-tools");
    expect(tools?.querySelectorAll("button")).toHaveLength(0);
    expect(tools?.querySelector(".journal-day-today")).toBeNull();
    const weekRow = document.querySelector(".sk-day-strip-weekrow");
    expect(weekRow?.querySelectorAll("button")).toHaveLength(2);
  });

  it("marks today with data-today and leaves other days unmarked", () => {
    render(<DayStrip {...props()} />);
    expect(dayButton(TODAY)).toHaveAttribute("data-today", "true");
    expect(dayButton(SELECTED)).not.toHaveAttribute("data-today");
  });

  it("marks the selected day as the current date and keeps one tab stop", () => {
    render(<DayStrip {...props()} />);
    expect(dayButton(SELECTED)).toHaveAttribute("aria-current", "date");
    expect(dayButton(SELECTED)).toHaveAttribute("tabindex", "0");
    expect(dayButton("2026-10-22")).not.toHaveAttribute("aria-current");
    expect(dayButton("2026-10-22")).toHaveAttribute("tabindex", "-1");
  });

  it("keeps every day cell at least 56 px high in px (it grows with large text), and the step arrows without an inline size", () => {
    render(<DayStrip {...props()} />);
    for (const button of screen.getAllByRole("button")) {
      if (button.hasAttribute("data-date")) {
        expect(button.style.minHeight).toBe("56px");
        expect(button.style.height).toBe("");
      } else {
        // The arrows take their 44 px box and 48 px target from the family icon-button rule (family.css).
        expect(button.style.height).toBe("");
        expect(button.style.minHeight).toBe("");
      }
    }
  });

  it("keeps both step arrows, with › aria-disabled on today", () => {
    render(<DayStrip {...props()} />);
    const next = screen.getByRole("button", { name: "Next week" });
    expect(
      screen.getByRole("button", { name: "Previous week" }),
    ).toBeInTheDocument();
    // Both arrows always show (a lone ‹ read as Back); the look is measured in journal-styles-mcp-app.spec.ts.
    expect(next).toHaveAttribute("aria-disabled", "true");
  });

  it("sets no inline width on the day buttons, so the equal tracks of the stylesheet apply", () => {
    render(<DayStrip {...props()} />);
    for (const button of screen.getAllByRole("button")) {
      // An inline minWidth would override the equal tracks (measured in journal-styles-mcp-app.spec.ts).
      expect(button.style.minWidth).toBe("");
    }
  });

  it("shows nothing for the week when the selected date is malformed", () => {
    render(<DayStrip {...props({ selected: "bogus" })} />);
    expect(document.querySelectorAll("button[data-date]")).toHaveLength(0);
    expect(document.querySelector("p.journal-day-range")).toBeNull();
  });
});

describe("DayStrip selection", () => {
  it("selects a day when it is clicked", async () => {
    const user = userEvent.setup();
    const base = props();
    render(<DayStrip {...base} />);
    await user.click(dayButton("2026-10-23"));
    expect(base.onSelect).toHaveBeenCalledWith("2026-10-23");
  });

  it("steps a week with the arrow buttons: previous week, then next week", async () => {
    const user = userEvent.setup();
    const base = props();
    const { rerender } = render(<DayStrip {...base} />);
    await user.click(screen.getByRole("button", { name: "Previous week" }));
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-14");
    // The parent passes the new week back; the week shown then does not hold today, so › is live again.
    rerender(<DayStrip {...base} selected="2026-10-14" />);
    await user.click(screen.getByRole("button", { name: "Next week" }));
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-21");
  });

  it("steps a week with a horizontal swipe: left to the next week, right to the previous", () => {
    const base = props({ selected: "2026-10-14" });
    const { rerender } = render(<DayStrip {...base} />);
    const strip = screen.getByRole("group", { name: "Week" });
    swipe(strip, [200, 100], [120, 104]);
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-21");
    rerender(<DayStrip {...base} selected="2026-10-21" />);
    swipe(strip, [100, 100], [180, 110]);
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-14");
  });

  it("ignores a short swipe, a mostly vertical one and any swipe while disabled", () => {
    const base = props();
    const { rerender } = render(<DayStrip {...base} />);
    const strip = screen.getByRole("group", { name: "Week" });
    swipe(strip, [200, 100], [170, 100]);
    swipe(strip, [200, 100], [240, 220]);
    expect(base.onSelect).not.toHaveBeenCalled();

    rerender(<DayStrip {...base} disabled />);
    swipe(strip, [200, 100], [100, 100]);
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("does not swipe past today", () => {
    const base = props({ selected: TODAY });
    render(<DayStrip {...base} />);
    swipe(screen.getByRole("group", { name: "Week" }), [200, 100], [100, 100]);
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("moves to the neighbouring day with the arrow keys and keeps focus on it", async () => {
    const user = userEvent.setup();
    const base = props();
    const { rerender } = render(<DayStrip {...base} />);
    dayButton(SELECTED).focus();

    await user.keyboard("{ArrowRight}");
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-22");

    // The parent passes the new day back; focus follows it to the same date button.
    rerender(<DayStrip {...base} selected="2026-10-22" />);
    expect(dayButton("2026-10-22")).toHaveFocus();

    await user.keyboard("{ArrowLeft}");
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-21");
  });

  it("moves across a week boundary with the arrow keys", async () => {
    const user = userEvent.setup();
    const base = props({ selected: "2026-10-19" });
    const { rerender } = render(<DayStrip {...base} />);
    dayButton("2026-10-19").focus();

    await user.keyboard("{ArrowLeft}");
    expect(base.onSelect).toHaveBeenLastCalledWith("2026-10-18");

    rerender(<DayStrip {...base} selected="2026-10-18" />);
    expect(dayButton("2026-10-18")).toHaveFocus();
  });

  it("ignores the arrow keys with a modifier", async () => {
    const user = userEvent.setup();
    const base = props();
    render(<DayStrip {...base} />);
    dayButton(SELECTED).focus();
    await user.keyboard("{Alt>}{ArrowRight}{/Alt}");
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("does nothing while disabled", async () => {
    const user = userEvent.setup();
    const base = props({ disabled: true });
    render(<DayStrip {...base} />);
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
    dayButton(SELECTED).focus();
    await user.keyboard("{ArrowRight}");
    expect(base.onSelect).not.toHaveBeenCalled();
  });
});

describe("DayStrip labels", () => {
  it("uses Swedish texts and short weekday names for sv", () => {
    render(<DayStrip {...props({ labels: dayStripLabelsSv })} />);
    expect(screen.getByRole("group", { name: "Veckan" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Föregående vecka" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Nästa vecka" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /har anteckningar$/ }),
    ).toHaveLength(2);
    const weekdays = WEEK.map(
      (date) =>
        dayButton(date).querySelector(".sk-day-strip-weekday")?.textContent,
    );
    // Today (the last day) says "Idag" in its weekday place, not "sön".
    expect(weekdays).toEqual([
      "mån",
      "tis",
      "ons",
      "tors",
      "fre",
      "lör",
      "Idag",
    ]);
    const numbers = WEEK.map(
      (date) =>
        dayButton(date).querySelector(".sk-day-strip-number")?.textContent,
    );
    expect(numbers).toEqual(["19", "20", "21", "22", "23", "24", "25"]);
  });

  it("names each day with its weekday, day and month (the words the cell shows come first), then vald and har anteckningar", () => {
    render(<DayStrip {...props({ labels: dayStripLabelsSv })} />);
    expect(dayButton(SELECTED)).toHaveAccessibleName("ons 21 oktober, vald");
    expect(dayButton("2026-10-20")).toHaveAccessibleName(
      "tis 20 oktober, har anteckningar",
    );
    expect(dayButton("2026-10-22")).toHaveAccessibleName("tors 22 oktober");
  });

  it("uses English texts for en", () => {
    render(<DayStrip {...props()} />);
    expect(screen.getByRole("group", { name: "Week" })).toBeInTheDocument();
    // The Today button is on the view's heading row, not in the strip.
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
  });

  it("keeps the Swedish and English key sets identical", () => {
    expect(Object.keys(dayStripLabelsSv).sort()).toEqual(
      Object.keys(dayStripLabelsEn).sort(),
    );
  });
});

describe("DayStrip week steps and days after today", () => {
  it("offers one set of step arrows, by week, and no separate nav", () => {
    render(<DayStrip {...props()} />);
    expect(document.querySelectorAll(".sk-day-strip-arrow")).toHaveLength(2);
    expect(document.querySelector(".sk-day-strip-nav")).toBeNull();
  });

  it("shows no day after today: the strip ends on today", () => {
    render(
      <DayStrip {...props({ selected: "2026-10-19", today: "2026-10-21" })} />,
    );
    const shown = Array.from(
      document.querySelectorAll<HTMLButtonElement>("button[data-date]"),
      (button) => button.dataset.date,
    );
    expect(shown).toEqual(sevenEndingOn("2026-10-21"));
    expect(dayButton("2026-10-21")).toBeEnabled();
    expect(document.querySelector('button[data-date="2026-10-22"]')).toBeNull();
    // The shown week holds today, so › is aria-disabled (not disabled); a press does nothing (next tests).
    const next = screen.getByRole("button", { name: "Next week" });
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(next).toBeEnabled();
  });

  it("keeps the next week in place on today as aria-disabled, not disabled, and a press does nothing", async () => {
    const user = userEvent.setup();
    const base = props({ selected: TODAY });
    render(<DayStrip {...base} />);
    const next = screen.getByRole("button", { name: "Next week" });
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(next).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous week" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Previous week" }),
    ).not.toHaveAttribute("aria-disabled");
    await user.click(next);
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("does not move to a day after today with the arrow keys", async () => {
    const user = userEvent.setup();
    const base = props({ selected: "2026-10-21", today: "2026-10-21" });
    render(<DayStrip {...base} />);
    dayButton("2026-10-21").focus();
    await user.keyboard("{ArrowRight}");
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("keeps › in the week that holds today as aria-disabled, and a press does nothing", async () => {
    const user = userEvent.setup();
    const earlier = shiftDate(TODAY, -1);
    const base = props({ selected: earlier });
    render(<DayStrip {...base} />);
    const next = screen.getByRole("button", { name: "Next week" });
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(next).toBeEnabled();
    await user.click(next);
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("a swipe forward in the week that holds today changes nothing, as › does there", () => {
    // Today is Sunday 25 October, and 19 October is the first day of the week that ends on today. A week forward
    // would be 26 October, so it is not offered: the swipe does what the aria-disabled › does, nothing.
    const base = props({ selected: "2026-10-19" });
    render(<DayStrip {...base} />);
    swipe(screen.getByRole("group", { name: "Week" }), [200, 100], [100, 100]);
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("a swipe forward on today itself changes nothing either", () => {
    const base = props({ selected: TODAY });
    render(<DayStrip {...base} />);
    swipe(screen.getByRole("group", { name: "Week" }), [200, 100], [100, 100]);
    expect(base.onSelect).not.toHaveBeenCalled();
  });

  it("a swipe forward from the week before today stops on today, not past it", () => {
    // 18 October ends the week before the one that ends on today, so a week forward lands on 25 October, which is
    // today. The stop is the last day offered.
    const base = props({ selected: "2026-10-18" });
    render(<DayStrip {...base} />);
    swipe(screen.getByRole("group", { name: "Week" }), [200, 100], [100, 100]);
    expect(base.onSelect).toHaveBeenCalledTimes(1);
    expect(base.onSelect).toHaveBeenCalledWith(TODAY);
  });

  it("keeps both step arrows on today, with the next one aria-disabled", () => {
    render(<DayStrip {...props({ selected: TODAY })} />);
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(screen.getByRole("button", { name: "Previous week" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next week" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});

describe("weekRange, the week the arrows step, named under them", () => {
  it("names a week within one month as its day numbers and the month: 2–8 nov", () => {
    expect(weekRange(sevenEndingOn("2026-11-08"), "sv-SE")).toBe("2–8 nov");
  });

  it("names a week across two months with both dates: 29 okt–4 nov", () => {
    expect(weekRange(sevenEndingOn("2026-11-04"), "sv-SE")).toBe(
      "29 okt–4 nov",
    );
  });

  it("uses the English month names for en: 29 Oct–4 Nov", () => {
    expect(weekRange(sevenEndingOn("2026-11-04"), "en-GB")).toBe(
      "29 Oct–4 Nov",
    );
    expect(weekRange(sevenEndingOn("2026-11-08"), "en-GB")).toBe("2–8 Nov");
  });

  it("is empty for an empty week", () => {
    expect(weekRange([], "sv-SE")).toBe("");
  });
});

describe("DayStrip with no day chosen", () => {
  it("marks the strip, has no current date, and still selects a day on tap", async () => {
    const onSelect = vi.fn();
    render(<DayStrip {...props({ unmarked: true, onSelect })} />);
    expect(document.querySelector(".sk-day-strip")).toHaveAttribute(
      "data-unmarked",
      "true",
    );
    expect(document.querySelector("[aria-current]")).toBeNull();
    await userEvent.click(dayButton("2026-10-22"));
    expect(onSelect).toHaveBeenCalledWith("2026-10-22");
  });

  it("draws no dots: they mark days with any entry, which would read as hits in a tagged list", () => {
    const withDots = props({ daysWithEntries: ["2026-10-22"] });
    const { unmount } = render(<DayStrip {...withDots} />);
    expect(dayButton("2026-10-22")).toHaveAttribute("data-has-entries", "true");
    unmount();
    render(<DayStrip {...props({ ...withDots, unmarked: true })} />);
    expect(dayButton("2026-10-22")).not.toHaveAttribute("data-has-entries");
    expect(document.querySelector(".sk-day-strip-dot")).toBeNull();
  });

  it("is marked unmarked only when no day is chosen", () => {
    const { unmount } = render(<DayStrip {...props()} />);
    expect(document.querySelector(".sk-day-strip")).not.toHaveAttribute(
      "data-unmarked",
    );
    unmount();
    render(<DayStrip {...props({ unmarked: true })} />);
    expect(document.querySelector(".sk-day-strip")).toHaveAttribute(
      "data-unmarked",
      "true",
    );
  });
});
