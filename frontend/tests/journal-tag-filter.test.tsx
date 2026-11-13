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

/** A tagged entry on its own day, older ids first as the server lists them. */
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
    const listTaggedEntries = vi
      .fn()
      .mockResolvedValueOnce(
        page([onDay(1, "2026-03-02"), onDay(2, "2026-05-09")], "c1"),
      )
      .mockResolvedValueOnce(page([onDay(3, "2026-09-30")]));
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
    expect(titles).toEqual(["Post 3", "Post 2", "Post 1"]);
    // The day leads each row's meta line, since the list spans days; the day's own content is gone.
    expect(screen.getByRole("button", { name: /Post 2/ })).toHaveTextContent(
      "9 May 2026",
    );
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
      await screen.findByText(journalEn.taggedEmpty(2)),
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
      await screen.findByText(journalEn.taggedEmpty(1)),
    ).toBeInTheDocument();

    await user.click(
      within(filterGroup()).getByRole("button", { name: "Clear tag filter" }),
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
    expect(screen.getByText(journalSv.taggedEmpty(1))).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Filtrera på tagg" }),
    ).toBeInTheDocument();
  });
});
