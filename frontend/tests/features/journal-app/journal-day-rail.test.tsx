// The Journal in a wide frame (desktop spec 3.2): the list pane is a rail (the month calendar, the day's rows, the tags,
// «Gjort») and the day is read beside it, in the shell's aside. The shell's panes are simulated with the room's context
// (`pane: "list"` and an aside element), so this is not a proof in the real Claude or Android host.
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import type { JournalFrame } from "@/features/journal-app/transport";
import {
  RoomSurfaceContext,
  type RoomSurface,
} from "@/features/mcp-apps/ui/room-context";
import {
  dayRoot,
  emptyDay,
  entry,
  entryId,
  otherEntry,
  otherEntryId,
  source,
  transportMock,
  type TransportMock,
} from "@tests/helpers/journal-app-fixtures";

// Monday 2 November 2026: the fixtures' day, Saturday 24 October, lies before it.
const NOW = new Date("2026-11-02T12:00:00Z");

let aside: HTMLElement;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  aside = document.createElement("aside");
  document.body.append(aside);
});

afterEach(() => {
  vi.useRealTimers();
  aside.remove();
});

function renderRail(
  transport: TransportMock,
  options: {
    initial?: JournalFrame;
    surface?: Partial<RoomSurface>;
    labels?: typeof journalEn;
    onTellClaude?: (text?: string) => void;
    onRoute?: () => void;
  } = {},
) {
  return render(
    <RoomSurfaceContext.Provider
      value={{
        active: true,
        framed: true,
        pane: "list",
        asideSlot: aside,
        ...options.surface,
      }}
    >
      <JournalView
        transport={transport}
        initial={options.initial ?? dayRoot}
        labels={options.labels ?? journalEn}
        fullscreen
        onRoute={options.onRoute}
        onTellClaude={options.onTellClaude}
      />
    </RoomSurfaceContext.Provider>,
  );
}

describe("the Journal's day in a wide frame", () => {
  it("puts the calendar and the day's rows in the list pane and reads the day in the aside", async () => {
    const { container } = renderRail(transportMock());
    const rail = within(container);
    const read = within(aside);

    // The list pane: the calendar replaces the strip, and the entries are compact rows with their time.
    expect(rail.getByRole("group", { name: "Calendar" })).toBeInTheDocument();
    expect(container.querySelector(".sk-day-strip")).toBeNull();
    expect(
      rail.getByRole("heading", { level: 3, name: "Entries" }),
    ).toBeInTheDocument();
    expect(
      container.querySelector(".journal-rail-card .journal-rail-time"),
    ).not.toBeNull();
    // The day's heading is not in the rail: it stands first in the reading pane.
    expect(rail.queryByRole("heading", { level: 2 })).toBeNull();
    expect(
      read.getByRole("heading", { level: 2, name: "Saturday 24 October" }),
    ).toBeInTheDocument();
    // The owner's own text is read in full; Claude's summary of the entry is not shown here.
    // (Both fixture entries read the same original.)
    expect(
      await read.findAllByText("Råtext: Anna vill ha offerten före fredag."),
    ).toHaveLength(2);
    expect(read.queryByText(entry.summary as string)).toBeNull();
    expect(read.getByText("Dagen handlade om offerten.")).toBeInTheDocument();
    // Every entry of the day is there, its title a button that opens it.
    expect(read.getByRole("button", { name: entry.title })).toBeInTheDocument();
    expect(read.getAllByRole("article")).toHaveLength(2);
  });

  it("opens an entry from its title in the reading pane and from its row, and draws the open one chosen", async () => {
    const user = userEvent.setup();
    const onRoute = vi.fn();
    const { container } = renderRail(transportMock(), {
      onRoute,
      surface: { beside: `journal:entry:${entryId}` },
    });

    const row = within(container).getByRole("button", { name: /Mötet om/ });
    expect(row.closest("li")).toHaveAttribute("aria-current", "true");
    await user.click(row);
    expect(onRoute).toHaveBeenLastCalledWith({
      room: "journal",
      view: "entry",
      id: entryId,
    });
    await user.click(
      within(aside).getByRole("button", { name: otherEntry.title }),
    );
    expect(onRoute).toHaveBeenLastCalledWith({
      room: "journal",
      view: "entry",
      id: otherEntryId,
    });
  });

  it("draws the old strip and nothing in the aside outside a split list", () => {
    const { container } = renderRail(transportMock(), {
      surface: { pane: "single", asideSlot: null },
    });

    expect(container.querySelector(".sk-day-strip")).not.toBeNull();
    expect(
      within(container).queryByRole("group", { name: "Calendar" }),
    ).toBeNull();
    expect(aside).toBeEmptyDOMElement();
    expect(
      within(container).getByRole("heading", {
        level: 2,
        name: "Saturday 24 October",
      }),
    ).toBeInTheDocument();
  });

  it("draws the rail but no reading pane while an entry is open beside the list", () => {
    const { container } = renderRail(transportMock(), {
      surface: { asideSlot: null, beside: `journal:entry:${entryId}` },
    });

    expect(
      within(container).getByRole("group", { name: "Calendar" }),
    ).toBeInTheDocument();
    expect(aside).toBeEmptyDOMElement();
  });

  it("shows an empty day's sentence and its ways to write in the reading pane", () => {
    const transport = transportMock({
      writeEntry: vi.fn(),
    });
    const { container } = renderRail(transport, {
      initial: { kind: "day", page: emptyDay("2026-10-24") },
      onTellClaude: vi.fn(),
    });

    expect(
      within(container).queryByRole("heading", { level: 3, name: "Entries" }),
    ).toBeNull();
    expect(within(aside).getByText(journalEn.noEntries)).toBeInTheDocument();
    expect(
      within(aside).getByRole("button", { name: journalEn.writeYourself }),
    ).toBeInTheDocument();
  });

  it("steps the day with ← and →, never past today, and goes to today with t", async () => {
    const transport = transportMock();
    renderRail(transport);

    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-23");
    expect(
      await within(aside).findByRole("heading", {
        level: 2,
        name: "Friday 23 October",
      }),
    ).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "t" });
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-11-02");
    await within(aside).findByRole("heading", {
      level: 2,
      name: "Monday 2 November",
    });
    // Today is the newest day there is: → stays where it is.
    transport.getDay.mockClear();
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    fireEvent.keyDown(document.body, { key: "]" });
    expect(transport.getDay).not.toHaveBeenCalled();
  });

  it("steps the day with ← and → in the narrow frame too", async () => {
    const transport = transportMock();
    render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
        fullscreen
      />,
    );

    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-25");
    await screen.findByRole("heading", { level: 2, name: "Sunday 25 October" });
    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-24");
  });

  it("chooses a day from the calendar and shows it, with its dot decided by what was read", async () => {
    const user = userEvent.setup();
    const transport = transportMock({
      listEntryDates: vi.fn(() => Promise.resolve(["2026-10-24"])),
    });
    const { container } = renderRail(transport);

    const cell = (date: string) =>
      container.querySelector<HTMLButtonElement>(`button[data-date="${date}"]`);
    expect(cell("2026-10-24")).toHaveAttribute("aria-current", "date");
    expect(cell("2026-10-24")).toHaveAttribute("data-has-entries", "true");
    await user.click(cell("2026-10-20") as HTMLButtonElement);
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-20");
    expect(
      await within(aside).findByRole("heading", {
        level: 2,
        name: "Tuesday 20 October",
      }),
    ).toBeInTheDocument();
    expect(cell("2026-10-20")).toHaveAttribute("aria-current", "date");
  });

  it("writes in the reading pane, not in the rail, and the rail's day stays put", async () => {
    const user = userEvent.setup();
    const { container } = renderRail(transportMock({ writeEntry: vi.fn() }));

    await user.click(screen.getByRole("button", { name: journalEn.addEntry }));
    expect(within(aside).getAllByRole("textbox").length).toBeGreaterThan(0);
    expect(within(container).queryByRole("textbox")).toBeNull();
    expect(
      within(container).getByRole("group", { name: "Calendar" }),
    ).toBeInTheDocument();
    // Escape with nothing written closes it, and the day is read again.
    fireEvent.keyDown(within(aside).getAllByRole("textbox")[0] as HTMLElement, {
      key: "Escape",
    });
    expect(within(aside).queryByRole("textbox")).toBeNull();
    expect(
      within(aside).getByRole("heading", {
        level: 2,
        name: "Saturday 24 October",
      }),
    ).toBeInTheDocument();
  });
});

describe("writing in a narrow frame", () => {
  it("puts the strip and the week's arrows away while writing, and brings them back", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <JournalView
        transport={transportMock({ writeEntry: vi.fn() })}
        initial={dayRoot}
        labels={journalEn}
        fullscreen
      />,
    );
    expect(container.querySelector(".sk-day-strip")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: journalEn.addEntry }));
    // The room head stays, with the form: no strip, no week arrows, no day heading above the form.
    expect(container.querySelector(".sk-room-head")).not.toBeNull();
    expect(container.querySelector(".sk-day-strip")).toBeNull();
    expect(container.querySelector(".sk-day-strip-weekrow")).toBeNull();
    expect(screen.getAllByRole("textbox").length).toBeGreaterThan(0);

    fireEvent.keyDown(screen.getAllByRole("textbox")[0] as HTMLElement, {
      key: "Escape",
    });
    expect(container.querySelector(".sk-day-strip")).not.toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("Tell Claude about the day", () => {
  it("is answered with a receipt in the day's bar from the empty day", async () => {
    const user = userEvent.setup();
    const onTellClaude = vi.fn();
    renderRail(transportMock(), {
      initial: { kind: "day", page: emptyDay("2026-10-24") },
      onTellClaude,
    });

    await user.click(
      within(aside).getByRole("button", { name: /^Send to Claude:/ }),
    );
    expect(onTellClaude).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Sent to Claude – answer in the chat"),
    ).toBeInTheDocument();
  });

  it("is answered with a receipt from the + of a day with entries, in Swedish", async () => {
    const user = userEvent.setup();
    const onTellClaude = vi.fn();
    render(
      <JournalView
        transport={transportMock()}
        initial={dayRoot}
        labels={journalSv}
        fullscreen
        onTellClaude={onTellClaude}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: journalSv.tellClaude }),
    );
    expect(onTellClaude).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Skickat till Claude – svara i chatten"),
    ).toBeInTheDocument();
  });
});

describe("the week in a wide frame", () => {
  it("fills the week in the calendar and reads it in the aside, with the room head once", async () => {
    const user = userEvent.setup();
    const { container } = renderRail(transportMock());

    await user.click(screen.getByRole("button", { name: journalEn.viewWeek }));
    expect(container.querySelectorAll("button[data-week]")).toHaveLength(7);
    // Saturday 24 October lies in the week of Monday 19 to Sunday 25 October, week 43.
    expect(
      await within(aside).findByRole("heading", {
        level: 2,
        name: /Week 43/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: journalEn.viewWeek }),
    ).toHaveLength(1);
    expect(within(container).queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("opens the day that is pressed in the calendar", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    const { container } = renderRail(transport);

    await user.click(screen.getByRole("button", { name: journalEn.viewWeek }));
    await within(aside).findByRole("heading", { level: 2, name: /Week 43/ });
    await user.click(
      container.querySelector(
        'button[data-date="2026-10-21"]',
      ) as HTMLButtonElement,
    );
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-21");
    expect(
      await within(aside).findByRole("heading", {
        level: 2,
        name: "Wednesday 21 October",
      }),
    ).toBeInTheDocument();
    expect(container.querySelector("button[data-week]")).toBeNull();
  });

  it("opens today with the form for a new entry from the week's +", async () => {
    const user = userEvent.setup();
    const { container } = renderRail(transportMock({ writeEntry: vi.fn() }));

    await user.click(screen.getByRole("button", { name: journalEn.viewWeek }));
    await within(aside).findByRole("heading", { level: 2, name: /Week 43/ });
    await user.click(screen.getByRole("button", { name: journalEn.addEntry }));
    expect(
      (await within(aside).findAllByRole("textbox")).length,
    ).toBeGreaterThan(0);
    expect(within(container).queryByRole("textbox")).toBeNull();
    // The form was today's: the entry it saves is written on Monday 2 November.
    expect(
      container.querySelector('button[data-date="2026-11-02"]'),
    ).toHaveAttribute("aria-current", "date");
  });
});

describe("stepping between entries", () => {
  function stepper() {
    return screen.findByRole("button", { name: /Next entry/ });
  }

  it("replaces the entry in the shell's layer instead of stacking another", async () => {
    const user = userEvent.setup();
    const onRoute = vi.fn();
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
        fullscreen
        onRoute={onRoute}
      />,
    );

    await user.click(await stepper());
    expect(onRoute).toHaveBeenCalledWith({
      room: "journal",
      view: "entry",
      id: otherEntryId,
      replace: true,
    });
  });

  it("replaces the entry in the view's own stack without a Back to climb", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
        fullscreen
      />,
    );

    await user.click(await stepper());
    expect(
      await screen.findByRole("heading", { level: 2, name: otherEntry.title }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: journalEn.back })).toBeNull();
    // The original of the first entry was read for it, and the source stays the fixtures'.
    expect(source.id).toBeTruthy();
  });

  it("has no keys of its own inline", async () => {
    const transport = transportMock();
    render(
      <JournalView
        transport={transport}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
      />,
    );
    await stepper();
    fireEvent.keyDown(document.body, { key: "j" });
    expect(
      screen.queryByRole("heading", { level: 2, name: otherEntry.title }),
    ).toBeNull();
  });
});
