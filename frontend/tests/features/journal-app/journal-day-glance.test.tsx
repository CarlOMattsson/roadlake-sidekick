import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { DayGlance } from "@/features/journal-app/day-glance";
import { formatDayHeading } from "@/features/journal-app/dates";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type {
  JournalDay,
  JournalEntry,
} from "@/features/journal-app/transport";
import { preloadSidekickApp } from "@tests/helpers/preload-sidekick-app";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;
type HostContextListener = (context: {
  locale?: string;
  displayMode?: string;
  availableDisplayModes?: string[];
}) => void;

// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  hostContext: [] as HostContextListener[],
  initialize: vi.fn(),
  call: vi.fn(),
  requestDisplayMode: vi.fn(),
  updateModelContext: vi.fn(),
}));

vi.mock("@/features/mcp-apps/bridge", () => ({
  createHostBridge: () => ({
    initialize: host.initialize,
    call: host.call,
    requestDisplayMode: host.requestDisplayMode,
    updateModelContext: host.updateModelContext,
    getFeatures: () => ({
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
    onToolInput: () => undefined,
    onToolCancelled: () => undefined,
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: (listener: HostContextListener) => {
      host.hostContext.push(listener);
    },
    onTeardown: () => undefined,
  }),
}));

// Today for the glance: the heading leaves out the year when it is the current one.
const TODAY = "2026-10-25";
const overview = "The client wants the quote before Friday.";
const entry: JournalEntry = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Meeting about the quote",
  summary: "Notes from the meeting.",
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  tags: [],
  archived: false,
  version: 1,
};
const day: JournalDay = {
  journal_date: "2026-10-24",
  entries: [entry],
  next_cursor: null,
  summary: {
    journal_date: "2026-10-24",
    exists: true,
    status: "current",
    content: { overview },
  },
};
const manyEntries: JournalDay = {
  ...day,
  entries: [1, 2, 3, 4, 5].map((n) => ({
    ...entry,
    id: `019f0000-0000-7000-8000-00000000000${n}`,
    title: `Entry ${n}`,
  })),
};
const pendingItems = [
  {
    source_id: "019f0000-0000-7000-8000-0000000000s2",
    journal_date: "2026-10-24",
    source_type: "manual_text",
    source_created_at: "2026-10-24T10:00:00Z",
    character_count: 120,
    state: "draft_pending_review",
    draft_id: "019f0000-0000-7000-8000-0000000000d1",
    draft_title: "Draft one",
  },
  {
    source_id: "019f0000-0000-7000-8000-0000000000s3",
    journal_date: "2026-10-24",
    source_type: "manual_text",
    source_created_at: "2026-10-24T11:00:00Z",
    character_count: 80,
    state: "draft_pending_review",
    draft_id: "019f0000-0000-7000-8000-0000000000d2",
    draft_title: "Draft two",
  },
  {
    source_id: "019f0000-0000-7000-8000-0000000000s4",
    journal_date: "2026-10-24",
    source_type: "manual_text",
    source_created_at: "2026-10-24T12:00:00Z",
    character_count: 40,
    state: "source_saved",
    draft_id: null,
    draft_title: null,
  },
];

describe("DayGlance", () => {
  it("shows the date, the overview, the counts and one Open button in English", () => {
    const onOpen = vi.fn();
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={day}
        draftCount={2}
        labels={journalEn}
        onOpen={onOpen}
      />,
    );

    expect(
      screen.getByRole("heading", {
        level: 2,
        name: formatDayHeading(day.journal_date, journalEn.dateLocale, TODAY),
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(overview)).toHaveClass("journal-card-summary");
    expect(screen.getByText("1 entry")).toBeInTheDocument();
    const review = screen.getByRole("button", { name: "Review 2 drafts" });
    expect(review).toHaveClass("sk-btn--secondary");
    expect(review.style.minHeight).toBe("44px");
    const open = screen.getByRole("button", { name: "Open" });
    // The open text button (44 high in family.css), no ink.
    expect(open).toHaveClass("sk-btn--open");
    // The one action, the review button and the entry row.
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("shows the Swedish labels and a plus sign when more entries exist", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={{
          ...day,
          entries: [
            entry,
            { ...entry, id: "019f0000-0000-7000-8000-0000000000e2" },
          ],
          next_cursor: "next",
        }}
        draftCount={1}
        labels={journalSv}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("2+ anteckningar")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Granska 1 utkast" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Öppna" })).toBeInTheDocument();
  });

  it("leaves the draft count out when it is not known", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={day}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("1 entry")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Review/ }),
    ).not.toBeInTheDocument();
  });

  it("leaves the review button and the zero count out when there are no drafts", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={day}
        draftCount={0}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.queryByText(/0 drafts|0 utkast/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Review/ }),
    ).not.toBeInTheDocument();
  });

  it("says so in the empty state when the day has no overview and no entries", () => {
    const { container } = render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={{
          ...day,
          entries: [],
          summary: { ...day.summary, content: null },
        }}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText(journalEn.noEntries)).toBeInTheDocument();
    expect(screen.queryByText(journalEn.noSummary)).not.toBeInTheDocument();
    expect(screen.queryByText(/^0 entries/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("p.journal-muted")).toHaveLength(0);
    expect(container.querySelector(".sk-empty-title")).toHaveTextContent(
      journalEn.noEntries,
    );
  });

  it("says nothing is written yet today, in Swedish too, for an empty today", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={{
          ...day,
          journal_date: TODAY,
          entries: [],
          summary: { ...day.summary, content: null },
        }}
        labels={journalSv}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("Inget skrivet idag än.")).toBeInTheDocument();
    expect(screen.queryByText(/0 anteckningar/)).not.toBeInTheDocument();
    expect(screen.queryByText(journalSv.noSummary)).not.toBeInTheDocument();
  });

  it("says nothing is written yet today in English for an empty today", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={{
          ...day,
          journal_date: TODAY,
          entries: [],
          summary: { ...day.summary, content: null },
        }}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("Nothing written yet today.")).toBeInTheDocument();
  });

  it("shows what was completed as one muted count line, in English and Swedish", () => {
    const withDone: JournalDay = {
      ...day,
      done: {
        tasks: [],
        steps: [],
        purchases: [],
        counts: { tasks: 1, steps: 1, purchases: 0 },
        truncated: false,
      },
    };
    const { unmount } = render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={withDone}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );
    const line = document.querySelector(".journal-glance-done");
    expect(line).toHaveClass("journal-muted");
    // The parts are joined with no-break spaces so that a part never breaks inside.
    expect(line?.textContent?.replace(/\u00a0/g, " ")).toBe(
      "Done · 1 task · 1 step",
    );
    unmount();

    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={withDone}
        labels={journalSv}
        onOpen={vi.fn()}
      />,
    );
    expect(
      document
        .querySelector(".journal-glance-done")
        ?.textContent?.replace(/\u00a0/g, " "),
    ).toBe("Gjort · 1 uppgift · 1 steg");
  });

  it("shows no completed line when every count is zero or the day has no done", () => {
    const { unmount } = render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={{
          ...day,
          done: {
            tasks: [],
            steps: [],
            purchases: [],
            counts: { tasks: 0, steps: 0, purchases: 0 },
            truncated: false,
          },
        }}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );
    expect(document.querySelector(".journal-glance-done")).toBeNull();
    unmount();

    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={day}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );
    expect(document.querySelector(".journal-glance-done")).toBeNull();
  });

  it("hides the no-summary line when the day has entries", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={{ ...day, summary: { ...day.summary, content: null } }}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.queryByText(journalEn.noSummary)).not.toBeInTheDocument();
  });

  it("opens the entry from its row, and the review button calls onReviewDrafts", async () => {
    const onOpenEntry = vi.fn();
    const onReviewDrafts = vi.fn();
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={onOpenEntry}
        onReviewDrafts={onReviewDrafts}
        day={day}
        draftCount={2}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /Meeting about the quote/ }),
    );
    expect(onOpenEntry).toHaveBeenCalledWith(entry.id);
    await userEvent.click(
      screen.getByRole("button", { name: "Review 2 drafts" }),
    );
    expect(onReviewDrafts).toHaveBeenCalledTimes(1);
  });

  it("lists the first three entries with their times, and says Show all when there are more", () => {
    render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={manyEntries}
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("Entry 3")).toBeInTheDocument();
    expect(screen.queryByText("Entry 4")).not.toBeInTheDocument();
    // Each shown entry has its time; the clock text depends on the test zone, so only the count is asserted.
    expect(document.querySelectorAll("time")).toHaveLength(3);
    expect(
      screen.getByRole("button", { name: journalEn.showAllEntries(5) }),
    ).toBeInTheDocument();
    // The three entry rows are buttons too, and so is the one action.
    expect(screen.getAllByRole("button")).toHaveLength(4);
    for (const title of ["Entry 1", "Entry 2", "Entry 3"]) {
      expect(
        screen.getByRole("button", { name: new RegExp(title) }),
      ).toHaveClass("journal-glance-row");
    }
  });

  it("calls onOpen once, and is busy and disabled while the host answers", async () => {
    const onOpen = vi.fn();
    const { rerender } = render(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={day}
        labels={journalEn}
        onOpen={onOpen}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(onOpen).toHaveBeenCalledTimes(1);

    rerender(
      <DayGlance
        today={TODAY}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        day={day}
        labels={journalEn}
        onOpen={onOpen}
        opening
      />,
    );
    const busy = screen.getByRole("button", { name: journalEn.cardOpening });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
  });
});

// The app's modules load at collection time, which has no timeout; the entry import in beforeAll then only
// runs the entry itself.
await preloadSidekickApp();

describe("journal day glance in the app", () => {
  beforeAll(async () => {
    // The app reads its language once, when sidekick-entry is imported, so the Sidekick setting goes in first.
    document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
    document.body.innerHTML = '<div id="root"></div>';
    host.initialize.mockResolvedValue({
      locale: "en-GB",
      displayMode: "inline",
      availableDisplayModes: ["inline", "fullscreen"],
    });
    await import("@/features/mcp-apps/sidekick-entry");
    // Initialize resolves on a microtask; until the first tool result the app shows the awaiting skeleton.
    await waitFor(() =>
      expect(
        document.querySelector('[role="status"][aria-busy="true"]'),
      ).not.toBeNull(),
    );
  });

  afterAll(() => {
    document.head.innerHTML = "";
  });

  beforeEach(() => {
    host.call.mockReset();
    host.call.mockImplementation((name: string) => {
      if (name === "list_pending_journal")
        return Promise.resolve({ items: pendingItems });
      return Promise.reject(new Error(`unexpected read ${name}`));
    });
    host.requestDisplayMode.mockReset();
    host.requestDisplayMode.mockResolvedValue("inline");
    host.updateModelContext.mockClear();
    setHostContext({
      locale: "en-GB",
      displayMode: "inline",
      availableDisplayModes: ["inline", "fullscreen"],
    });
  });

  it("shows the glance inline when fullscreen is offered, not the day view", async () => {
    deliver(day);

    expect(screen.getByText(overview)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Review 2 drafts" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 entry")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: journalEn.entries }),
    ).not.toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith("list_pending_journal", {
      from_date: day.journal_date,
      to_date: day.journal_date,
    });
  });

  it("asks the host for fullscreen from Open and shows the day view there", async () => {
    host.requestDisplayMode.mockResolvedValue("fullscreen");
    deliver(day);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
    expect(
      await screen.findByRole("heading", { level: 3, name: journalEn.entries }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open" }),
    ).not.toBeInTheDocument();
  });

  it("is busy while the host answers, then shows the day view", async () => {
    let answer: (mode: string) => void = () => undefined;
    host.requestDisplayMode.mockReturnValue(
      new Promise<string>((resolve) => {
        answer = resolve;
      }),
    );
    deliver(day);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(
      screen.getByRole("button", { name: journalEn.cardOpening }),
    ).toBeDisabled();

    act(() => {
      answer("fullscreen");
    });
    expect(
      await screen.findByRole("heading", { level: 3, name: journalEn.entries }),
    ).toBeInTheDocument();
  });

  it("falls back to the inline day view when the host refuses fullscreen", async () => {
    host.requestDisplayMode.mockResolvedValue("inline");
    deliver(day);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(
      await screen.findByRole("heading", { level: 3, name: journalEn.entries }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open" }),
    ).not.toBeInTheDocument();
  });

  it("falls back to the inline day view when the fullscreen request fails", async () => {
    host.requestDisplayMode.mockRejectedValue(new Error("host failure"));
    deliver(day);

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(
      await screen.findByRole("heading", { level: 3, name: journalEn.entries }),
    ).toBeInTheDocument();
  });

  it("shows the glance inline without fullscreen, and Open expands the day inline", async () => {
    setHostContext({ availableDisplayModes: ["inline"] });
    deliver(day);

    expect(
      await screen.findByRole("button", { name: "Review 2 drafts" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: journalEn.entries }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(
      await screen.findByRole("heading", { level: 3, name: journalEn.entries }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open" }),
    ).not.toBeInTheDocument();
    // Without fullscreen on offer, Open never asks the host for it.
    expect(host.requestDisplayMode).not.toHaveBeenCalled();
  });

  it("keeps the glance to three entries until Show all opens every entry inline", async () => {
    setHostContext({ availableDisplayModes: ["inline"] });
    deliver(manyEntries);

    expect(await screen.findByText(/Entry 3/)).toBeInTheDocument();
    expect(screen.queryByText(/Entry 4/)).not.toBeInTheDocument();
    expect(screen.getByText(overview)).toHaveClass("journal-card-summary");
    await userEvent.click(
      screen.getByRole("button", { name: journalEn.showAllEntries(5) }),
    );
    expect(await screen.findByText(/Entry 5/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: journalEn.showAllEntries(5) }),
    ).not.toBeInTheDocument();
  });

  it("asks the host for fullscreen from Show all when there are more than three entries", async () => {
    host.requestDisplayMode.mockResolvedValue("fullscreen");
    deliver(manyEntries);

    await userEvent.click(
      await screen.findByRole("button", {
        name: journalEn.showAllEntries(5),
      }),
    );

    expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
  });

  it("leaves the draft count out when the pending read fails", async () => {
    host.call.mockImplementation((name: string) =>
      name === "list_pending_journal"
        ? Promise.reject(new Error("upstream detail"))
        : Promise.reject(new Error(`unexpected read ${name}`)),
    );
    deliver(day);

    await waitFor(() =>
      expect(host.call).toHaveBeenCalledWith(
        "list_pending_journal",
        expect.anything(),
      ),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText("1 entry")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Review/ }),
    ).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("upstream detail");
  });

  it("opens an entry from its row, asking the host for fullscreen first", async () => {
    host.requestDisplayMode.mockResolvedValue("fullscreen");
    deliver(day);
    await userEvent.click(
      await screen.findByRole("button", { name: /Meeting about the quote/ }),
    );

    expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
    await waitFor(() =>
      expect(host.call).toHaveBeenCalledWith("get_journal_entry", {
        entry_id: entry.id,
        include_content: true,
      }),
    );
  });

  it("shows the day's drafts in the app from Review, reading the pending items once more", async () => {
    setHostContext({ availableDisplayModes: ["inline"] });
    deliver(day);
    await userEvent.click(
      await screen.findByRole("button", { name: "Review 2 drafts" }),
    );

    expect(
      await screen.findByText("Draft one", { exact: false }),
    ).toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith("list_pending_journal", {
      from_date: day.journal_date,
      to_date: day.journal_date,
    });
    expect(
      screen.queryByRole("heading", { level: 3, name: journalEn.entries }),
    ).not.toBeInTheDocument();
  });
});

/** Delivers a tool result to every listener the app registered, as the host would. */
function deliver(structuredContent: unknown, isError = false) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

function setHostContext(context: {
  locale?: string;
  displayMode?: string;
  availableDisplayModes?: string[];
}) {
  act(() => {
    for (const listener of host.hostContext) listener(context);
  });
}
