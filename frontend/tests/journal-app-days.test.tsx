import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { shiftDate } from "@/features/journal-app/dates";
import { JournalView } from "@/features/journal-app/journal-view";
import { rootFromToolResult } from "@/features/journal-app/transport";
import {
  entryId,
  entry,
  source,
  day,
  emptyDay,
  draftId,
  transportMock,
  dayRoot,
} from "./helpers/journal-app-fixtures";

describe("journal day strip dots and Tell Claude more", () => {
  it("marks every day with entries from one dates read for the seven shown days", async () => {
    // Today is Monday 2 November; 24 October is in the seven days that end on 26 October.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const listEntryDates = vi.fn(() => Promise.resolve(["2026-10-21"]));
      const transport = transportMock({ listEntryDates });
      render(
        <JournalView
          transport={transport}
          initial={dayRoot}
          labels={journalEn}
        />,
      );
      await waitFor(() =>
        expect(
          document.querySelector('button[data-date="2026-10-21"]'),
        ).toHaveAttribute("data-has-entries", "true"),
      );
      expect(listEntryDates).toHaveBeenCalledTimes(1);
      expect(listEntryDates).toHaveBeenCalledWith("2026-10-20", "2026-10-26");
      // The day the view has read has entries, so it keeps its dot even though the range read missed it.
      expect(
        document.querySelector('button[data-date="2026-10-24"]'),
      ).toHaveAttribute("data-has-entries", "true");
      expect(
        document.querySelector('button[data-date="2026-10-22"]'),
      ).not.toHaveAttribute("data-has-entries");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps only the read day's dot when the dates read fails", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const listEntryDates = vi.fn(() => Promise.reject(new Error("offline")));
      const transport = transportMock({ listEntryDates });
      render(
        <JournalView
          transport={transport}
          initial={dayRoot}
          labels={journalEn}
        />,
      );
      await waitFor(() => expect(listEntryDates).toHaveBeenCalledTimes(1));
      expect(document.querySelectorAll("[data-has-entries]")).toHaveLength(1);
      expect(
        document.querySelector('button[data-date="2026-10-24"]'),
      ).toHaveAttribute("data-has-entries", "true");
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers Tell Claude about the day as a round ink + in the title row before the ⋯ on a day with entries, naming the day in the message", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const user = userEvent.setup();
      const onTellClaude = vi.fn();
      render(
        <JournalView
          transport={transportMock()}
          initial={dayRoot}
          labels={journalEn}
          fullscreen
          onRoute={vi.fn()}
          onTellClaude={onTellClaude}
        />,
      );
      const more = screen.getByRole("button", {
        name: "Tell Claude about the day",
      });
      // The day's one primary is the + of the other rooms, in the title row's tools, right before ⋯.
      expect(more).toHaveClass(
        "sk-iconbtn",
        "sk-iconbtn--primary",
        "journal-day-add",
      );
      expect(more).toHaveAttribute("title", "Tell Claude about the day");
      expect(more.closest(".sk-day-strip-tools")).not.toBeNull();
      expect(more.nextElementSibling).toBe(
        screen.getByRole("button", { name: journalEn.moreActions }),
      );
      // No whole button in the content any more, and no hint.
      expect(document.querySelector(".journal-empty-state")).toBeNull();
      expect(screen.queryByText(journalEn.tellClaudeHint)).toBeNull();
      await user.click(more);
      expect(onTellClaude).toHaveBeenCalledTimes(1);
      expect(onTellClaude).toHaveBeenCalledWith(
        "I’d like to tell you more about Saturday 24 October so you can save it in my journal.",
      );
      expect(
        screen.queryByRole("button", { name: /^Send to Claude:/ }),
      ).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("sends the message without a date from today's +, with the date from another day's", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const user = userEvent.setup();
      const onTellClaude = vi.fn();
      render(
        <JournalView
          transport={transportMock()}
          initial={{ kind: "day", page: day("2026-11-02", [entry]) }}
          labels={journalEn}
          onTellClaude={onTellClaude}
        />,
      );
      await user.click(
        screen.getByRole("button", { name: "Tell Claude about the day" }),
      );
      expect(onTellClaude).toHaveBeenCalledWith(
        "I’d like to tell you more about my day so you can save it in my journal.",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("asks Claude through the example button, with no + and no Entries heading, on a day with only a summary", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const user = userEvent.setup();
      const onTellClaude = vi.fn();
      render(
        <JournalView
          transport={transportMock()}
          initial={{ kind: "day", page: day("2026-10-24", []) }}
          labels={journalEn}
          onTellClaude={onTellClaude}
        />,
      );
      expect(document.querySelector(".journal-day-add")).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Tell Claude about the day" }),
      ).toBeNull();
      // The old whole button and its hint are gone; the example is what is pressed.
      expect(document.querySelector(".journal-tell-more")).toBeNull();
      expect(screen.queryByText(journalEn.tellClaudeHint)).toBeNull();
      const message =
        "I’d like to tell you about Saturday 24 October so you can save it in my journal.";
      await user.click(
        screen.getByRole("button", { name: `Send to Claude: ${message}` }),
      );
      expect(onTellClaude).toHaveBeenCalledTimes(1);
      expect(onTellClaude).toHaveBeenCalledWith(message);
    } finally {
      vi.useRealTimers();
    }
  });

  it("draws the empty day as the family's empty state with no + and the example as the main thing", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      render(
        <JournalView
          transport={transportMock()}
          initial={{ kind: "day", page: emptyDay("2026-11-02") }}
          labels={journalEn}
          onTellClaude={vi.fn()}
        />,
      );
      expect(document.querySelector(".journal-day-add")).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Tell Claude about the day" }),
      ).toBeNull();
      expect(document.querySelector(".journal-tell-more")).toBeNull();
      const state = document.querySelector(".journal-empty-state");
      expect(state).not.toBeNull();
      expect(state?.querySelector(".sk-empty-title")).toHaveTextContent(
        journalEn.noEntriesToday,
      );
      expect(state?.querySelector(".sk-empty-ask-lead")).toHaveTextContent(
        "Tell Claude:",
      );
      expect(state?.querySelector(".sk-empty-example")).toHaveTextContent(
        journalEn.tellClaudeMessage,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows no Entries heading on an empty day, only the sentence and the example to send to Claude", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const user = userEvent.setup();
      const onTellClaude = vi.fn();
      render(
        <JournalView
          transport={transportMock()}
          initial={{ kind: "day", page: emptyDay("2026-11-02") }}
          labels={journalEn}
          onTellClaude={onTellClaude}
        />,
      );
      expect(
        screen.queryByRole("heading", { level: 3, name: journalEn.entries }),
      ).toBeNull();
      expect(screen.getByText(journalEn.noEntriesToday)).toHaveClass(
        "sk-empty-title",
      );
      await user.click(
        screen.getByRole("button", {
          name: `Send to Claude: ${journalEn.tellClaudeMessage}`,
        }),
      );
      expect(onTellClaude).toHaveBeenCalledTimes(1);
      expect(onTellClaude).toHaveBeenCalledWith(journalEn.tellClaudeMessage);
      // The old hint line is gone: no second sentence under the empty text.
      expect(screen.queryByText(/Tell Claude about your day/)).toBeNull();
      expect(screen.queryByText(journalEn.tellClaudeHint)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("names the lead and the example button in English and in Swedish", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 2, 12));
    try {
      const empty = { kind: "day" as const, page: emptyDay("2026-11-02") };
      const { unmount } = render(
        <JournalView
          transport={transportMock()}
          initial={empty}
          labels={journalEn}
          onTellClaude={vi.fn()}
        />,
      );
      expect(screen.getByText("Tell Claude:")).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: `Send to Claude: ${journalEn.tellClaudeMessage}`,
        }),
      ).toBeInTheDocument();
      unmount();
      render(
        <JournalView
          transport={transportMock()}
          initial={empty}
          labels={journalSv}
          onTellClaude={vi.fn()}
        />,
      );
      expect(screen.getByText("Säg till Claude:")).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: `Skicka till Claude: ${journalSv.tellClaudeMessage}`,
        }),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("hides Tell Claude about the day when the host cannot send messages", () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={dayRoot}
        labels={journalEn}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /Tell Claude about the day/ }),
    ).toBeNull();
    expect(document.querySelector(".journal-day-add")).toBeNull();
  });

  it("names the Swedish + Berätta för Claude om dagen and sends the Swedish message with the date", async () => {
    const user = userEvent.setup();
    const onTellClaude = vi.fn();
    render(
      <JournalView
        transport={transportMock()}
        initial={dayRoot}
        labels={journalSv}
        onTellClaude={onTellClaude}
      />,
    );
    const more = screen.getByRole("button", {
      name: "Berätta för Claude om dagen",
    });
    expect(more).toHaveClass(
      "sk-iconbtn",
      "sk-iconbtn--primary",
      "journal-day-add",
    );
    expect(more).toHaveAttribute("title", "Berätta för Claude om dagen");
    expect(document.querySelector(".journal-tell-more")).toBeNull();
    await user.click(more);
    expect(onTellClaude).toHaveBeenCalledTimes(1);
    expect(onTellClaude.mock.calls[0]![0]).toMatch(
      /^Jag vill berätta mer om .+ så att det sparas i dagboken\.$/,
    );
    expect(onTellClaude.mock.calls[0]![0]).toContain("24 oktober");
  });
});

describe("journal app errors", () => {
  it("shows calm text without retry when the day read is forbidden", async () => {
    const user = userEvent.setup();
    const transport = transportMock({
      getDay: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
    });
    render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Next week" }));
    expect(await screen.findByText(journalEn.forbidden)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Try again" }),
    ).not.toBeInTheDocument();
  });

  it("shows the shared notice under the day that failed, not the old day's entries", async () => {
    const user = userEvent.setup();
    const transport = transportMock({
      getDay: vi
        .fn()
        .mockRejectedValueOnce(new HostToolError("internal_error"))
        .mockResolvedValueOnce(day("2026-10-31", [])),
    });
    render(
      <JournalView
        transport={transport}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Next week" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load this right now",
    );
    // The heading names the day the owner tried to open, and the old day's entries are gone.
    expect(
      screen.getByRole("heading", { level: 2, name: "Saturday 31 October" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Mötet om offerten/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Dagen handlade om offerten."),
    ).not.toBeInTheDocument();
    // The day strip stays, so another day can be chosen.
    expect(
      screen.getByRole("button", { name: "Next week" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(journalEn.noEntries)).toBeInTheDocument();
    expect(transport.getDay).toHaveBeenLastCalledWith("2026-10-31");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers a retry for other entry failures and reads the entry again", async () => {
    const user = userEvent.setup();
    const getEntry = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockResolvedValueOnce({ entry });
    render(
      <JournalView
        transport={transportMock({ getEntry })}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Mötet om offerten/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load this right now",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Mötet om offerten",
      }),
    ).toBeInTheDocument();
    expect(getEntry).toHaveBeenCalledTimes(2);
  });

  it("shows calm text without retry when the entry is forbidden", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transportMock({
          getEntry: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
        })}
        initial={dayRoot}
        labels={journalEn}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Mötet om offerten/ }));
    expect(await screen.findByText(journalEn.forbidden)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Try again" }),
    ).not.toBeInTheDocument();
  });
});

describe("journal app roots", () => {
  it("roots a day, an entry and a pending list from their tool results only", () => {
    expect(
      rootFromToolResult({
        journal_date: "2026-10-24",
        entries: [entry],
        next_cursor: null,
        summary: { journal_date: "2026-10-24", exists: false },
      }),
    ).toMatchObject({ kind: "day", page: { journal_date: "2026-10-24" } });
    expect(rootFromToolResult({ entry })).toEqual({
      kind: "entry",
      id: entryId,
    });
    expect(rootFromToolResult({ items: [] })).toEqual({
      kind: "pending",
      page: { items: [] },
    });
    expect(rootFromToolResult({ draft: { id: draftId }, source })).toEqual({
      kind: "draft",
      id: draftId,
    });
    expect(rootFromToolResult({ source })).toBeUndefined();
    expect(
      rootFromToolResult({ journal_date: "2026-10-24", entries: [{}] }),
    ).toBeUndefined();
    expect(rootFromToolResult(undefined)).toBeUndefined();
  });

  it("moves calendar dates without a time zone shift", () => {
    expect(shiftDate("2026-03-01", -1)).toBe("2026-02-28");
    expect(shiftDate("2026-12-31", 1)).toBe("2027-01-01");
    expect(shiftDate("not-a-date", 1)).toBe("not-a-date");
  });

  it("shows an empty state when no root is open", async () => {
    render(<JournalView transport={transportMock()} labels={journalEn} />);
    await waitFor(() =>
      expect(screen.getByText(journalEn.empty)).toBeInTheDocument(),
    );
  });
});
