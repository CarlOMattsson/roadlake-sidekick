import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import type { JournalFrame } from "@/features/journal-app/transport";
import {
  entryId,
  sourceId,
  pendingRows,
  entry,
  source,
  day,
  transportMock,
  dayRoot,
} from "./helpers/journal-app-fixtures";

describe("journal app navigation", () => {
  it("moves from a day to an entry, its original, and back to the day", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "Saturday 24 October" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Dagen handlade om offerten.")).toBeInTheDocument();
    // The summary is an ingress with no heading under a muted meta line; the region keeps its name for
    // assistive technology, and the visible line is hidden from it so the name is not read twice.
    expect(
      screen.queryByRole("heading", { name: "The day in brief" }),
    ).not.toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "The day in brief" });
    expect(summary).toHaveTextContent("Dagen handlade om offerten.");
    expect(
      summary
        .querySelector(".journal-summary-label")
        ?.getAttribute("aria-hidden"),
    ).toBe("true");

    await user.click(screen.getByRole("button", { name: /Mötet om offerten/ }));
    expect(transport.getEntry).toHaveBeenCalledWith(entryId);
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Mötet om offerten",
      }),
    ).toHaveFocus();
    expect(
      screen.getByText("Kunden vill ha offerten före fredag."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Commitment: Skicka offerten på torsdag."),
    ).toBeInTheDocument();
    expect(screen.getByText("Projects: 1")).toBeInTheDocument();
    expect(screen.queryByText(/Tasks:/)).toBeNull();
    expect(screen.getByText("Contacts: 1")).toBeInTheDocument();

    // The entry says the original is saved, right under the summary.
    expect(screen.getByText(journalEn.summarizedNote)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show original" }));
    expect(transport.getSource).toHaveBeenCalledWith(sourceId);
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Your original text",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(journalEn.originalNote)).toBeInTheDocument();
    expect(
      screen.getByText("Råtext: Anna vill ha offerten före fredag."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show summary" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "Mötet om offerten" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(
      screen.getByRole("heading", { level: 2, name: "Saturday 24 October" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Back" }),
    ).not.toBeInTheDocument();
  });

  it("shows the day a week back in place of the current one", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    // The week arrow steps seven days: from 24 October back to 17 October.
    await user.click(screen.getByRole("button", { name: "Previous week" }));
    expect(transport.getDay).toHaveBeenCalledWith("2026-10-17");
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Saturday 17 October",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(journalEn.noEntries)).toBeInTheDocument();
    // The day a week back replaces the current one, so there is nothing to go back to.
    expect(
      screen.queryByRole("button", { name: "Back" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next week" }));
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-24");
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Saturday 24 October",
      }),
    ).toBeInTheDocument();
  });

  it("puts Today on the heading row and removes it while today is shown", async () => {
    // Pin only the clock, so today is 2 November and the shown day is 24 October.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const user = userEvent.setup();
      const transport = transportMock();
      render(
        <JournalView
          transport={transport}
          initial={dayRoot}
          labels={journalEn}
        />,
      );

      const idag = screen.getByRole("button", { name: "Today" });
      expect(idag).toHaveClass("journal-day-today", "sk-btn--compact");
      await user.click(idag);
      expect(transport.getDay).toHaveBeenLastCalledWith("2026-11-02");
      expect(
        await screen.findByRole("heading", {
          level: 2,
          name: "Monday 2 November",
        }),
      ).toBeInTheDocument();

      // On today there is nothing to go to: the button is gone, not greyed.
      expect(
        screen.queryByRole("button", { name: "Today" }),
      ).not.toBeInTheDocument();
      expect(transport.getDay).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps Today out while the seven shown days already include today, even on another day", () => {
    // Today is Monday 2 November; the seven days that end on it include 30 October. The strip's own cell for
    // today is the way back, so the Today button is not offered.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const transport = transportMock();
      render(
        <JournalView
          transport={transport}
          initial={{ kind: "day", page: day("2026-10-30", []) }}
          labels={journalEn}
        />,
      );

      expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
      expect(
        document.querySelector('button[data-date="2026-11-02"]'),
      ).toHaveAttribute("data-today", "true");
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows no original on a day row and reads none: the entry view reads the original", () => {
    const transport = transportMock();
    render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Show original" }),
    ).not.toBeInTheDocument();
    expect(transport.getSource).not.toHaveBeenCalled();
  });

  it("steps the day with [ and ] and jumps to today with t", async () => {
    // Pin only the clock, not the timers, so "today" is a known date and not the day the suite runs.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const transport = transportMock();
      render(
        <JournalView
          transport={transport}
          initial={dayRoot}
          labels={journalEn}
          fullscreen
        />,
      );

      fireEvent.keyDown(document.body, { key: "[" });
      expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-23");
      expect(
        await screen.findByRole("heading", {
          level: 2,
          name: "Friday 23 October",
        }),
      ).toBeInTheDocument();

      fireEvent.keyDown(document.body, { key: "]" });
      expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-24");
      expect(
        await screen.findByRole("heading", {
          level: 2,
          name: "Saturday 24 October",
        }),
      ).toBeInTheDocument();

      fireEvent.keyDown(document.body, { key: "t" });
      expect(transport.getDay).toHaveBeenLastCalledWith("2026-11-02");
      expect(
        await screen.findByRole("heading", {
          level: 2,
          name: "Monday 2 November",
        }),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("steps the day with ] only when fullscreen is set", async () => {
    const transport = transportMock();
    const { rerender } = render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    fireEvent.keyDown(document.body, { key: "]" });
    expect(transport.getDay).not.toHaveBeenCalled();

    rerender(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
        fullscreen
      />,
    );
    fireEvent.keyDown(document.body, { key: "]" });
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-25");
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Sunday 25 October",
      }),
    ).toBeInTheDocument();
  });

  it("opens the day's ⋯ in fullscreen, where Minne och kontroll routes to the control room, and has no ⋯ without a route", async () => {
    const user = userEvent.setup();
    const transport = transportMock();
    const onRoute = vi.fn();
    const { rerender } = render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
        fullscreen
        onRoute={onRoute}
      />,
    );
    const more = screen.getByRole("button", { name: journalEn.moreActions });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    // The panel's one entry. The app locale is Swedish when the page declares none, so the label is "Minne och kontroll".
    const control = screen.getByRole("button", { name: "Minne och kontroll" });
    // Escape closes the panel and gives the focus back to ⋯.
    fireEvent.keyDown(control, { key: "Escape" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveFocus();
    expect(onRoute).not.toHaveBeenCalled();

    await user.click(more);
    await user.click(
      screen.getByRole("button", { name: "Minne och kontroll" }),
    );
    expect(onRoute).toHaveBeenCalledTimes(1);
    expect(onRoute).toHaveBeenCalledWith({ room: "control", view: "memory" });

    // Without a route (an inline day, or a host without navigation) there is no ⋯ at all.
    rerender(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
        fullscreen
      />,
    );
    expect(
      screen.queryByRole("button", { name: journalEn.moreActions }),
    ).toBeNull();
  });

  it("holds the update reminder in the day's ⋯ when the Control room is off, even without a route", async () => {
    const user = userEvent.setup();
    const built = new Date(Date.now() - 20 * 24 * 60 * 60 * 1000).toISOString();
    document.head.innerHTML =
      '<meta name="sidekick-rooms" content="work,journal">' +
      '<meta name="sidekick-build-commit" content="abc1234">' +
      `<meta name="sidekick-build-date" content="${built}">` +
      '<meta name="sidekick-update-days" content="14">';
    try {
      render(
        <JournalView
          transport={transportMock()}
          initial={dayRoot}
          labels={journalEn}
          fullscreen
        />,
      );
      const more = screen.getByRole("button", {
        name: `${journalEn.moreActions} – uppdatering finns att hämta`,
      });
      await user.click(more);
      expect(
        screen.getByText(/Sidekick är 20 dagar gammal/),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Minne och kontroll" }),
      ).not.toBeInTheDocument();
      await user.click(
        screen.getByRole("button", {
          name: "Påminn inte för den här versionen",
        }),
      );
      // The dot is gone; the button the owner just used stays to hold the line that says so.
      expect(
        screen.getByRole("button", { name: journalEn.moreActions }),
      ).toBeInTheDocument();
      expect(screen.getByRole("status")).toBeInTheDocument();
    } finally {
      document.head.innerHTML = "";
      localStorage.clear();
      delete document.documentElement.dataset.updateDismissed;
    }
  });

  it("adds the fullscreen class to the root only when fullscreen is set", () => {
    const transport = transportMock();
    const { container, rerender } = render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );
    expect(container.querySelector(".sidekick-journal")).not.toHaveClass(
      "journal-fullscreen",
    );

    rerender(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
        fullscreen
      />,
    );
    expect(container.querySelector(".sidekick-journal")).toHaveClass(
      "journal-fullscreen",
    );
  });

  it("marks an archived entry on its day row with the archived label", () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={dayRoot}
        labels={journalSv}
      />,
    );

    const archivedRow = screen
      .getByRole("button", { name: /Injected/ })
      .closest("li");
    expect(archivedRow).not.toBeNull();
    expect(
      within(archivedRow as HTMLElement).getByText(/Arkiverad/),
    ).toBeInTheDocument();

    const activeRow = screen
      .getByRole("button", { name: /Mötet om offerten/ })
      .closest("li");
    expect(activeRow).not.toBeNull();
    expect(
      within(activeRow as HTMLElement).queryByText(/Arkiverad/),
    ).not.toBeInTheDocument();
  });

  it("says so when an entry has no original text", async () => {
    const user = userEvent.setup();
    const transport = transportMock({
      getSource: vi.fn(() =>
        Promise.resolve({ source: { ...source, raw_text: null } }),
      ),
    });
    render(
      <JournalView
        transport={transport}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: "Show original" }),
    );
    expect(
      await screen.findByText(journalEn.originalEmpty),
    ).toBeInTheDocument();
  });

  it("shows the entry title once in the entry view when the summary starts with it", async () => {
    const transport = transportMock({
      getEntry: vi.fn(() =>
        Promise.resolve({
          entry: {
            ...entry,
            summary: "Mötet om offerten: vi enades om rabatten.",
          },
        }),
      ),
    });
    render(
      <JournalView
        transport={transport}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
      />,
    );

    expect(
      await screen.findByRole("heading", { level: 2, name: entry.title }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(entry.title, { exact: false })).toHaveLength(1);
    expect(screen.getByText("vi enades om rabatten.")).toHaveClass(
      "journal-summary",
    );
  });

  it("renders a pending root with the review note and one button per draft", () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={{
          kind: "pending",
          page: {
            items: [
              {
                source_id: sourceId,
                journal_date: "2026-10-24",
                source_type: "transcript_text",
                source_created_at: "2026-10-24T09:31:00Z",
                character_count: 42,
                state: "draft_pending_review",
                draft_id: "019f0000-0000-7000-8000-0000000000d1",
                draft_title: "Utkast om offerten",
              },
            ],
          },
        }}
        labels={journalEn}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "Awaiting review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Open a draft to review it. Nothing is saved until you save it.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Utkast om offerten" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("shows three pending items inline and the rest in place with Show all", async () => {
    const items = pendingRows(10);
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "pending", page: { items } }}
        labels={journalEn}
      />,
    );

    expect(screen.getByRole("button", { name: "Draft 2" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Draft 3" }),
    ).not.toBeInTheDocument();
    const more = screen.getByRole("button", {
      name: journalEn.pendingMore(7),
    });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more.style.minHeight).toBe("44px");

    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Draft 9" })).toBeInTheDocument();
    const less = screen.getByRole("button", { name: journalEn.pendingLess });
    expect(less).toHaveAttribute("aria-expanded", "true");
  });

  it("shows every pending item in fullscreen, with no Show all", () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "pending", page: { items: pendingRows(10) } }}
        labels={journalEn}
        fullscreen
      />,
    );

    expect(screen.getByRole("button", { name: "Draft 9" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: journalEn.pendingMore(7) }),
    ).not.toBeInTheDocument();
  });

  it("renders the Swedish pending note for the Swedish host locale", () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "pending", page: { items: [] } }}
        labels={journalSv}
      />,
    );

    expect(
      screen.getByText(
        "Öppna ett utkast för att granska det. Inget sparas förrän du väljer det.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(journalSv.pendingEmpty)).toBeInTheDocument();
  });

  it("shows readable source and state labels and a grouped character count", () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={{
          kind: "pending",
          page: {
            items: [
              {
                source_id: sourceId,
                journal_date: "2026-10-26",
                source_type: "transcript_text",
                source_created_at: "2026-10-26T09:31:00Z",
                character_count: 1840,
                state: "draft_pending_review",
                draft_id: null,
                draft_title: null,
              },
            ],
          },
        }}
        labels={journalSv}
      />,
    );

    expect(
      screen.getByText("26 okt. 2026 · Transkription"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Utkast som väntar på granskning · 1 840 tecken"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/transcript_text|draft_pending_review/),
    ).toBeNull();
  });

  it("names a source without a draft in words, never as the raw value", () => {
    const pendingPage: JournalFrame = {
      kind: "pending",
      page: {
        items: [
          {
            source_id: sourceId,
            journal_date: "2026-10-26",
            source_type: "manual_text",
            source_created_at: "2026-10-26T09:31:00Z",
            character_count: 90,
            state: "source_saved",
            draft_id: null,
            draft_title: null,
          },
        ],
      },
    };
    const { unmount } = render(
      <JournalView
        transport={transportMock()}
        initial={pendingPage}
        labels={journalSv}
      />,
    );
    expect(
      screen.getByText("Sparad, ej granskad · 90 tecken"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/source_saved/)).toBeNull();
    unmount();

    render(
      <JournalView
        transport={transportMock()}
        initial={pendingPage}
        labels={journalEn}
      />,
    );
    expect(
      screen.getByText("Saved, not reviewed · 90 characters"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/source_saved/)).toBeNull();
  });

  it("lists only the linked kinds that have entries in an entry view", async () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
      />,
    );

    // The fixture links one project and one contact and no task.
    expect(await screen.findByText("Projects: 1")).toBeInTheDocument();
    expect(screen.getByText("Contacts: 1")).toBeInTheDocument();
    expect(screen.queryByText(/Tasks:/)).toBeNull();
    expect(
      screen.getByRole("heading", { level: 3, name: "Linked" }),
    ).toBeInTheDocument();
  });

  it("hides the whole Linked block when the entry links nothing", async () => {
    const transport = transportMock({
      getEntry: vi.fn(() =>
        Promise.resolve({
          entry: {
            ...entry,
            project_ids: [],
            task_ids: [],
            contact_ids: [],
          },
        }),
      ),
    });
    render(
      <JournalView
        transport={transport}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
      />,
    );

    expect(
      await screen.findByRole("button", { name: "Show original" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Linked" })).toBeNull();
    expect(screen.queryByText(/: 0$/)).toBeNull();
  });

  it("keeps entry text as plain text, never as markup", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <JournalView
        transport={transportMock()}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Injected/ }));
    await screen.findByRole("heading", {
      level: 2,
      name: "Injected <img src=x onerror=alert(1)>",
    });
    expect(container.querySelector("img")).toBeNull();
  });
});
