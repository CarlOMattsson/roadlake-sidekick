import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { shiftDate } from "@/features/journal-app/dates";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type { JournalTaggedPage } from "@/features/journal-app/tag-transport";
import type {
  JournalEntry,
  JournalTransport,
} from "@/features/journal-app/transport";
import { ownerToday } from "@/features/mcp-apps/app-timezone";
import {
  day,
  entry,
  transportMock,
  type TransportMock,
} from "./helpers/journal-app-fixtures";
import {
  listTagsMock,
  tagRecord,
  taggedEntry,
} from "./helpers/journal-tag-fixtures";

const dayRoot = {
  kind: "day" as const,
  page: day("2026-10-24", [entry]),
};

function renderDay(transport: TransportMock, labels = journalEn) {
  return render(
    <JournalView transport={transport} initial={dayRoot} labels={labels} />,
  );
}

/** A tagged entry on its own day. */
function onDay(
  n: number,
  journalDate: string,
  tags = ["viktig"],
): JournalEntry {
  return taggedEntry(tags, {
    id: `019f0000-0000-7000-8000-00000000f${n}`,
    title: `Post ${n}`,
    journal_date: journalDate,
    occurred_at: null,
    summary: null,
  });
}

function page(
  entries: JournalEntry[],
  next: string | null = null,
): JournalTaggedPage {
  return { entries, next_cursor: next };
}

const filterGroup = () => screen.getByRole("group", { name: "Filter by tag" });

describe("the tag filter of the day view", () => {
  it("offers the tags in use on entries, most used first, and none that only other kinds use", async () => {
    renderDay(
      transportMock({
        listTags: listTagsMock(),
        listTaggedEntries: vi.fn(() => Promise.resolve(page([]))),
      }),
    );
    const group = await screen.findByRole("group", { name: "Filter by tag" });
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Viktig", "Familj"]);
    expect(within(group).queryByRole("button", { name: "Vänta" })).toBeNull();
  });

  it("is not drawn without tags in use, without the vocabulary or without the tagged read", async () => {
    const read = vi.fn(() => Promise.resolve(page([])));
    const unused = listTagsMock([tagRecord("vanta", "Vänta", 0)]);
    const { unmount } = renderDay(
      transportMock({ listTags: unused, listTaggedEntries: read }),
    );
    await waitFor(() => expect(unused).toHaveBeenCalled());
    expect(screen.queryByRole("group", { name: "Filter by tag" })).toBeNull();
    unmount();

    const noVocabulary = renderDay(transportMock({ listTaggedEntries: read }));
    expect(screen.queryByRole("group", { name: "Filter by tag" })).toBeNull();
    noVocabulary.unmount();

    const noRead = listTagsMock();
    renderDay(transportMock({ listTags: noRead }));
    await waitFor(() => expect(noRead).toHaveBeenCalled());
    expect(screen.queryByRole("group", { name: "Filter by tag" })).toBeNull();
    expect(read).not.toHaveBeenCalled();
  });

  it("reads the last 12 months for every chosen tag, newest first, and following the cursor", async () => {
    const user = userEvent.setup();
    const thisYear = Number(ownerToday(undefined).slice(0, 4));
    const listTaggedEntries = vi
      .fn()
      .mockResolvedValueOnce(
        page(
          [onDay(1, `${thisYear}-01-02`), onDay(2, `${thisYear - 1}-05-09`)],
          "c1",
        ),
      )
      .mockResolvedValueOnce(page([onDay(3, "2024-09-30")]));
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await screen.findByRole("group", { name: "Filter by tag" });

    await user.click(screen.getByRole("button", { name: "Viktig" }));

    expect(
      await screen.findByRole("heading", { name: journalEn.taggedEntries }),
    ).toBeInTheDocument();
    const today = ownerToday(undefined);
    expect(listTaggedEntries).toHaveBeenNthCalledWith(
      1,
      ["viktig"],
      shiftDate(today, -365),
      today,
      null,
    );
    expect(listTaggedEntries).toHaveBeenNthCalledWith(
      2,
      ["viktig"],
      shiftDate(today, -365),
      today,
      "c1",
    );
    const titles = (
      await screen.findAllByRole("button", { name: /^Post/ })
    ).map((b) => within(b).getByText(/^Post \d/).textContent);
    // The server lists newest first; the list keeps that order across pages.
    expect(titles).toEqual(["Post 1", "Post 2", "Post 3"]);
    // The day leads each row's meta line, since the list spans days; the year only when it is not this year.
    expect(screen.getByRole("button", { name: /Post 2/ })).toHaveTextContent(
      `9 May ${thisYear - 1}`,
    );
    const thisYearRow = screen.getByRole("button", { name: /Post 1/ });
    expect(thisYearRow).toHaveTextContent("2 Jan");
    expect(thisYearRow).not.toHaveTextContent(String(thisYear));
    // The day's own content is gone.
    expect(screen.queryByText("Dagen handlade om offerten.")).toBeNull();
    expect(
      screen.queryByRole("heading", { name: journalEn.entries }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Viktig" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("narrows to entries with every chosen tag", async () => {
    const user = userEvent.setup();
    const listTaggedEntries = vi.fn<
      NonNullable<JournalTransport["listTaggedEntries"]>
    >(() => Promise.resolve(page([])));
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await user.click(screen.getByRole("button", { name: "Familj" }));

    await waitFor(() => expect(listTaggedEntries).toHaveBeenCalledTimes(2));
    expect(listTaggedEntries.mock.calls[1]?.[0]).toEqual(["viktig", "familj"]);
    expect(
      await screen.findByText(journalEn.taggedNone(2, 1)),
    ).toBeInTheDocument();
  });

  it("says so when nothing is tagged, and Clear brings the day back", async () => {
    const user = userEvent.setup();
    renderDay(
      transportMock({
        listTags: listTagsMock(),
        listTaggedEntries: vi.fn(() => Promise.resolve(page([]))),
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    expect(
      await screen.findByText(journalEn.taggedNone(1, 1)),
    ).toBeInTheDocument();

    await user.click(
      within(filterGroup()).getByRole("button", { name: "Clear (1)" }),
    );

    expect(
      screen.queryByRole("heading", { name: journalEn.taggedEntries }),
    ).toBeNull();
    expect(
      screen.getByRole("heading", { name: journalEn.entries }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Viktig" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    // "Clear" is gone with the press: the focus stays in the filter, on its first tag, not on the page.
    expect(screen.getByRole("button", { name: "Viktig" })).toHaveFocus();
  });

  it("shows a failed read with Try again, which reads once more", async () => {
    const user = userEvent.setup();
    const listTaggedEntries = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(page([onDay(1, "2026-09-30")]));
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load this right now",
    );

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(
      await screen.findByRole("button", { name: /Post 1/ }),
    ).toBeInTheDocument();
    expect(listTaggedEntries).toHaveBeenCalledTimes(2);
  });

  it("says that the list was cut when it runs past ten pages", async () => {
    const user = userEvent.setup();
    const listTaggedEntries = vi.fn(() =>
      Promise.resolve(page([onDay(1, "2026-09-30")], "more")),
    );
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));

    expect(
      await screen.findByText(journalEn.taggedCapped(10)),
    ).toBeInTheDocument();
    expect(listTaggedEntries).toHaveBeenCalledTimes(10);
  });

  it("draws 50 entries at a time and says the list was cut only once all of them are drawn", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 120 }, (_, n) => onDay(n, "2026-09-30"));
    const listTaggedEntries = vi
      .fn()
      .mockResolvedValueOnce(page(many.slice(0, 50), "p2"))
      .mockResolvedValueOnce(page(many.slice(50, 100), "p3"))
      .mockResolvedValueOnce(page(many.slice(100), "p4"))
      .mockImplementation(() => Promise.resolve(page([], "more")));
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText("Post 0");
    const rows = () => screen.getAllByRole("button", { name: /^Post/ });

    expect(rows()).toHaveLength(50);
    expect(screen.queryByText(/^Showing the newest/)).toBeNull();
    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    expect(rows()).toHaveLength(100);
    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    expect(rows()).toHaveLength(120);
    expect(screen.getByText(journalEn.taggedCapped(120))).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: journalEn.taggedMore }),
    ).toBeNull();
    // Draws and queries 120 rows by name: a few seconds alone, longer on a loaded runner.
  }, 60_000);

  it("opens an entry of the list, and Back returns to the list with the tag still chosen", async () => {
    const user = userEvent.setup();
    const getEntry = vi.fn(() =>
      Promise.resolve({ entry: onDay(1, "2026-09-30") }),
    );
    const listTaggedEntries = vi.fn(() =>
      Promise.resolve(page([onDay(1, "2026-09-30")])),
    );
    renderDay(
      transportMock({ getEntry, listTags: listTagsMock(), listTaggedEntries }),
    );
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await user.click(await screen.findByRole("button", { name: /Post 1/ }));
    await screen.findByRole("heading", { level: 2, name: "Post 1" });

    await user.click(screen.getByRole("button", { name: journalEn.back }));

    expect(
      await screen.findByRole("button", { name: /Post 1/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Viktig" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("leaves the list when another day is chosen in the strip", async () => {
    const user = userEvent.setup();
    const getDay = vi.fn((date: string) => Promise.resolve(day(date, [])));
    renderDay(
      transportMock({
        getDay,
        listTags: listTagsMock(),
        listTaggedEntries: vi.fn(() =>
          Promise.resolve(page([onDay(1, "2026-09-30")])),
        ),
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByRole("button", { name: /Post 1/ });

    await user.click(screen.getByRole("button", { name: /^Sun 25 October/ }));

    await waitFor(() => expect(getDay).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: journalEn.taggedEntries }),
      ).toBeNull(),
    );
  });

  it("lets the rows of the plain day carry their tags, by label once the vocabulary is read", async () => {
    render(
      <JournalView
        transport={transportMock({ listTags: listTagsMock() })}
        initial={{
          kind: "day",
          page: day("2026-10-24", [taggedEntry(["viktig"])]),
        }}
        labels={journalEn}
      />,
    );
    expect(await screen.findByText("Tags: Viktig")).toBeInTheDocument();
  });

  it("speaks Swedish, with the same parts", async () => {
    const user = userEvent.setup();
    renderDay(
      transportMock({
        listTags: listTagsMock(),
        listTaggedEntries: vi.fn(() => Promise.resolve(page([]))),
      }),
      journalSv,
    );
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    expect(
      await screen.findByRole("heading", { name: journalSv.taggedEntries }),
    ).toBeInTheDocument();
    expect(screen.getByText(journalSv.taggedNone(1, 1))).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Filtrera på tagg" }),
    ).toBeInTheDocument();
  });
});

describe("the tagged list in place of the day", () => {
  it("names the view by the list and marks no day of the strip", async () => {
    const user = userEvent.setup();
    renderDay(
      transportMock({
        listTags: listTagsMock(),
        listTaggedEntries: vi.fn(() =>
          Promise.resolve(page([onDay(1, "2026-09-30")])),
        ),
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText("Post 1");
    const headings = screen.getAllByRole("heading", {
      name: journalEn.taggedEntries,
    });
    expect(headings).toHaveLength(1);
    expect(headings[0]?.tagName).toBe("H2");
    expect(document.querySelector('[aria-current="date"]')).toBeNull();
  });

  it("reads the year before the oldest with Show more, under the list, until a year is empty", async () => {
    const user = userEvent.setup();
    const listTaggedEntries = vi
      .fn()
      .mockResolvedValueOnce(page([onDay(1, "2026-09-30")]))
      .mockResolvedValueOnce(page([onDay(2, "2025-06-01")]))
      .mockResolvedValueOnce(page([]));
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText("Post 1");

    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    await screen.findByText("Post 2");
    const today = ownerToday(undefined);
    const to = shiftDate(today, -366);
    expect(listTaggedEntries).toHaveBeenNthCalledWith(
      2,
      ["viktig"],
      shiftDate(to, -365),
      to,
      null,
    );
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Post 1")).toBeLessThan(text.indexOf("Post 2"));
    expect(
      screen.getByText(
        "Entries tagged Viktig from the last 2 years, newest first",
      ),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    expect(
      await screen.findByText(journalEn.taggedNoOlder(1)),
    ).toBeInTheDocument();
    const older = shiftDate(today, -732);
    expect(listTaggedEntries).toHaveBeenLastCalledWith(
      ["viktig"],
      shiftDate(older, -365),
      older,
      null,
    );
    // One empty year still offers the year before it.
    expect(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    ).toBeInTheDocument();
  });

  it("ends the list after two empty years in a row: no Show more, a sentence that says how far back it read", async () => {
    const user = userEvent.setup();
    const listTaggedEntries = vi
      .fn()
      .mockResolvedValueOnce(page([onDay(1, "2026-09-30")]))
      .mockResolvedValueOnce(page([]))
      .mockResolvedValueOnce(page([]));
    renderDay(transportMock({ listTags: listTagsMock(), listTaggedEntries }));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText("Post 1");
    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    await screen.findByText(journalEn.taggedNoOlder(1));
    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    expect(
      await screen.findByText(journalEn.taggedStopped(1)),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: journalEn.taggedMore }),
    ).toBeNull();
    expect(listTaggedEntries).toHaveBeenCalledTimes(3);
  });

  it("ends at once when the last 12 months and the year before are both empty", async () => {
    const user = userEvent.setup();
    const listTaggedEntries = vi.fn(() => Promise.resolve(page([])));
    renderDay(
      transportMock({ listTags: listTagsMock(), listTaggedEntries }),
      journalSv,
    );
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText(journalSv.taggedNone(1, 1));
    await user.click(
      screen.getByRole("button", { name: journalSv.taggedMore }),
    );
    // Nothing was found, so the empty line names the two years read and nothing claims there is "no older" entry.
    expect(
      await screen.findByText(journalSv.taggedNone(1, 2)),
    ).toBeInTheDocument();
    expect(screen.queryByText(journalSv.taggedStopped(1))).toBeNull();
    expect(
      screen.queryByRole("button", { name: journalSv.taggedMore }),
    ).toBeNull();
    expect(
      screen.getByText(
        "Anteckningar med taggen Viktig från de senaste 2 åren, nyast först",
      ),
    ).toBeInTheDocument();
  });

  it("offers no + while a tag is chosen, and + is back with the day once the filter is cleared", async () => {
    const user = userEvent.setup();
    renderDay(
      transportMock({
        listTags: listTagsMock(),
        listTaggedEntries: vi.fn(() =>
          Promise.resolve(page([onDay(1, "2026-09-30")])),
        ),
        writeEntry: vi.fn(),
      }),
    );
    expect(
      await screen.findByRole("button", { name: journalEn.addEntry }),
    ).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText("Post 1");
    expect(
      screen.queryByRole("button", { name: journalEn.addEntry }),
    ).toBeNull();
    await user.click(
      within(filterGroup()).getByRole("button", { name: "Clear (1)" }),
    );
    expect(
      await screen.findByRole("button", { name: journalEn.addEntry }),
    ).toBeInTheDocument();
  });
});
