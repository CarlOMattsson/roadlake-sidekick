import { act, screen, waitFor } from "@testing-library/react";
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
import { formatDayHeading } from "@/features/journal-app/dates";
import { journalEn } from "@/features/journal-app/labels";
import type {
  JournalDay,
  JournalEntry,
} from "@/features/journal-app/transport";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;
type HostContextListener = (context: {
  locale?: string;
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
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: (listener: HostContextListener) => {
      host.hostContext.push(listener);
    },
    onTeardown: () => undefined,
  }),
}));

const createdId = "019f0000-0000-7000-8000-0000000000e1";
const summaryText = "Kunden vill ha offerten före fredag.";
const created: JournalEntry = {
  id: createdId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: summaryText,
  key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
  project_ids: [],
  task_ids: ["019f0000-0000-7000-8000-0000000000t1"],
  contact_ids: [
    "019f0000-0000-7000-8000-0000000000c1",
    "019f0000-0000-7000-8000-0000000000c2",
  ],
  tags: [],
  archived: false,
  version: 1,
};

const dayResult: JournalDay = {
  journal_date: "2026-10-24",
  entries: [created],
  next_cursor: null,
  summary: {
    journal_date: "2026-10-24",
    exists: false,
    status: null,
    content: null,
  },
};

/** Delivers a tool result to every listener the app registered, as the host would. */
function deliver(structuredContent: unknown, isError = false) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

function setHostContext(context: {
  locale?: string;
  availableDisplayModes?: string[];
}) {
  act(() => {
    for (const listener of host.hostContext) listener(context);
  });
}

afterAll(() => {
  document.head.innerHTML = "";
  vi.useRealTimers();
});

beforeAll(async () => {
  // Today is pinned (the Date only, timers stay real), so "today", "yesterday" and the year rule are fixed.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-03T12:00:00"));
  // The app reads its language once, when sidekick-entry is imported, so the Sidekick setting goes in first.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({
    locale: "en-GB",
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

beforeEach(() => {
  host.call.mockReset();
  host.call.mockImplementation((name: string) =>
    name === "get_journal_entry"
      ? Promise.resolve({ entry: created })
      : Promise.reject(new Error(`unexpected read ${name}`)),
  );
  host.updateModelContext.mockClear();
  host.requestDisplayMode.mockReset();
  host.requestDisplayMode.mockResolvedValue("inline");
  setHostContext({
    locale: "en-GB",
    availableDisplayModes: ["inline", "fullscreen"],
  });
});

describe("journal entry card", () => {
  it("shows a compact card for a create result with title, clamped summary and link counts", () => {
    deliver({ entry: created });

    expect(
      screen.getByRole("heading", { level: 2, name: created.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(summaryText)).toHaveClass("journal-card-summary");
    // One muted meta line: the summary note, then the counts (a result without links).
    expect(
      document.querySelector(".sk-card__meta.journal-card-links")?.textContent,
    ).toBe("Summarized by Claude · 2 contacts · 1 task");
    // Every part after the first leads with its «·» in a box of its own, which journal.css clips away when the part
    // starts a wrapped line (ui-13); the first part has no «·».
    const parts = document.querySelectorAll(".journal-card-links > span");
    expect(
      Array.from(parts, (part) =>
        Boolean(part.firstElementChild?.classList.contains("journal-card-sep")),
      ),
    ).toEqual([false, true, true]);
    expect(
      screen.getByRole("button", { name: "Open entry" }),
    ).toBeInTheDocument();
    // The card shows no key points and reads nothing; the entry text stays out of the model.
    expect(
      screen.queryByText("Skicka offerten på torsdag."),
    ).not.toBeInTheDocument();
    expect(host.call).not.toHaveBeenCalled();
    expect(host.updateModelContext).not.toHaveBeenCalled();
  });

  it("draws the card at first render from the result record, with no read and no loading state", () => {
    deliver({ entry: created });

    expect(
      screen.getByRole("heading", { level: 2, name: created.title }),
    ).toBeInTheDocument();
    expect(host.call).not.toHaveBeenCalled();
    expect(screen.queryByText(journalEn.loading)).not.toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("reads the entry by id as before when the record fails validation", async () => {
    deliver({ entry: { ...created, summary: 42 } });

    expect(
      await screen.findByRole("heading", { level: 3, name: "Key points" }),
    ).toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith("get_journal_entry", {
      entry_id: createdId,
      include_content: true,
    });
  });

  it("opens the existing entry view from Open without sending entry text to the model or the console", async () => {
    const consoleMethods = ["log", "info", "warn", "error", "debug"] as const;
    const spies = consoleMethods.map((method) =>
      vi.spyOn(console, method).mockImplementation(() => undefined),
    );
    try {
      deliver({ entry: created });
      await userEvent.click(screen.getByRole("button", { name: "Open entry" }));

      expect(
        await screen.findByRole("heading", { level: 3, name: "Key points" }),
      ).toBeInTheDocument();
      expect(host.call).toHaveBeenCalledWith("get_journal_entry", {
        entry_id: createdId,
        include_content: true,
      });
      expect(
        screen.queryByRole("button", { name: "Open entry" }),
      ).not.toBeInTheDocument();
      expect(host.updateModelContext).not.toHaveBeenCalled();
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });

  it("asks the host for fullscreen from Open and shows the entry there", async () => {
    host.requestDisplayMode.mockResolvedValue("fullscreen");
    deliver({ entry: created });
    await userEvent.click(screen.getByRole("button", { name: "Open entry" }));

    expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
    expect(
      await screen.findByRole("heading", { level: 3, name: "Key points" }),
    ).toBeInTheDocument();
    // Full mode tells the model which room is open, and which record the card is on.
    expect(host.updateModelContext).toHaveBeenCalledWith(
      `Viewing Journal (id ${createdId})`,
    );
  });

  it("falls back to the inline entry view when the host refuses fullscreen", async () => {
    host.requestDisplayMode.mockResolvedValue("inline");
    deliver({ entry: created });
    await userEvent.click(screen.getByRole("button", { name: "Open entry" }));

    expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
    expect(
      await screen.findByRole("heading", { level: 3, name: "Key points" }),
    ).toBeInTheDocument();
  });

  it("falls back to the inline entry view when the fullscreen request fails, without logging the entry", async () => {
    const consoleMethods = ["log", "info", "warn", "error", "debug"] as const;
    const spies = consoleMethods.map((method) =>
      vi.spyOn(console, method).mockImplementation(() => undefined),
    );
    try {
      host.requestDisplayMode.mockRejectedValue(
        new Error("Host request failed"),
      );
      deliver({ entry: created });
      await userEvent.click(screen.getByRole("button", { name: "Open entry" }));

      expect(
        await screen.findByRole("heading", { level: 3, name: "Key points" }),
      ).toBeInTheDocument();
      expect(host.updateModelContext).not.toHaveBeenCalled();
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });

  it("opens the entry inline without asking when the host does not offer fullscreen", async () => {
    setHostContext({ availableDisplayModes: ["inline"] });
    deliver({ entry: created });
    await userEvent.click(screen.getByRole("button", { name: "Open entry" }));

    expect(host.requestDisplayMode).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("heading", { level: 3, name: "Key points" }),
    ).toBeInTheDocument();
  });

  it("says saved with the date and the time the result carries, without 'at'", () => {
    deliver({ entry: { ...created, occurred_at: "2026-10-24T14:05:00" } });
    expect(screen.getByText("saved 24 Oct 14:05")).toBeInTheDocument();
  });

  it("says saved with the time for today, saved yesterday with the time, and the date only for other days", () => {
    deliver({
      entry: {
        ...created,
        journal_date: "2026-11-03",
        occurred_at: "2026-11-03T12:30:00",
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^saved 12:30$/);

    deliver({
      entry: {
        ...created,
        journal_date: "2026-11-02",
        occurred_at: "2026-11-02T18:05:00",
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      /^saved yesterday 18:05$/,
    );

    deliver({
      entry: { ...created, journal_date: "2025-12-31", occurred_at: null },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^saved 31 Dec 2025$/);
  });

  it("says saved today without a time when the result carries none", () => {
    deliver({
      entry: { ...created, journal_date: "2026-11-03", occurred_at: null },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^saved today$/);
  });

  it("does not repeat a summary that is the title again, ignoring case and spaces", () => {
    deliver({ entry: { ...created, summary: "  mötet OM offerten " } });

    expect(
      screen.getByRole("heading", { level: 2, name: created.title }),
    ).toBeInTheDocument();
    expect(
      document.querySelector(".journal-card-summary"),
    ).not.toBeInTheDocument();
  });

  it("shows only the rest of a summary that starts with the title", () => {
    deliver({
      entry: {
        ...created,
        summary: "Mötet om offerten: vi enades om rabatten.",
      },
    });

    expect(screen.getByText("vi enades om rabatten.")).toHaveClass(
      "journal-card-summary",
    );
    expect(
      screen.queryByText("Mötet om offerten: vi enades om rabatten."),
    ).not.toBeInTheDocument();
  });

  it("keeps the whole summary when the title is only the start of a longer word", () => {
    deliver({
      entry: {
        ...created,
        title: "Möte",
        summary: "Mötesanteckningar från dagen.",
      },
    });

    expect(screen.getByText("Mötesanteckningar från dagen.")).toHaveClass(
      "journal-card-summary",
    );
  });

  it("makes Open busy, disabled and relabelled while the host answers the fullscreen request", async () => {
    let answer: (mode: string) => void = () => undefined;
    host.requestDisplayMode.mockReturnValue(
      new Promise<string>((resolve) => {
        answer = resolve;
      }),
    );
    deliver({ entry: created });
    await userEvent.click(screen.getByRole("button", { name: "Open entry" }));

    const busy = screen.getByRole("button", { name: "Opening…" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toBeDisabled();
    expect(host.requestDisplayMode).toHaveBeenCalledTimes(1);

    act(() => {
      answer("inline");
    });

    expect(
      await screen.findByRole("heading", { level: 3, name: "Key points" }),
    ).toBeInTheDocument();
    expect(host.requestDisplayMode).toHaveBeenCalledTimes(1);
  });

  it("says plainly when the entry has no links", () => {
    deliver({ entry: { ...created, contact_ids: [], task_ids: [] } });

    expect(document.querySelector(".journal-card-links")?.textContent).toBe(
      "Summarized by Claude · Not linked to anything yet",
    );
  });

  it("keeps the other result forms unchanged and clears the card when one arrives", async () => {
    // The app's today is the pinned clock of this file.
    const glanceDate = formatDayHeading(
      dayResult.journal_date,
      journalEn.dateLocale,
      "2026-11-03",
    );
    deliver({ entry: created });
    deliver(dayResult);

    // With fullscreen offered, the day shows its glance in place of the card, not the day list.
    expect(
      screen.getByRole("heading", { level: 2, name: glanceDate }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 entry")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: created.title }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: journalEn.entries }),
    ).not.toBeInTheDocument();

    // An error result keeps the view that is shown.
    deliver({ entry: created }, true);
    expect(
      screen.getByRole("heading", { level: 2, name: glanceDate }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: created.title }),
    ).not.toBeInTheDocument();

    // A single entry without a title is not a card: it opens the entry view as before.
    deliver({ entry: { id: createdId } });
    expect(
      await screen.findByRole("heading", { level: 3, name: "Linked" }),
    ).toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith("get_journal_entry", {
      entry_id: createdId,
      include_content: true,
    });
    expect(
      screen.queryByRole("button", { name: "Open entry" }),
    ).not.toBeInTheDocument();

    // Without fullscreen offered, the same day result shows the glance inline too; Open expands the day.
    setHostContext({ availableDisplayModes: ["inline"] });
    deliver(dayResult);
    expect(
      screen.getByRole("heading", { level: 2, name: glanceDate }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: journalEn.entries }),
    ).not.toBeInTheDocument();
    // The glance is the only journal-card.
    expect(document.querySelectorAll(".journal-card")).toHaveLength(1);
    // The glance's own action (the day), not the card's "Open entry".
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(
      await screen.findByRole("heading", { level: 3, name: journalEn.entries }),
    ).toBeInTheDocument();
    // The card's name starts with its time, then the title.
    expect(
      screen.getByRole("button", { name: new RegExp(created.title) }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open" }),
    ).not.toBeInTheDocument();
  });

  it("says the summary is Claude's in the meta line, with no Show original in the card and no read", () => {
    deliver({ entry: created });

    expect(screen.getByText(journalEn.cardSummarized)).toBeInTheDocument();
    expect(screen.queryByText(journalEn.summarizedNote)).toBeNull();
    expect(screen.queryByText(journalEn.originalSavedNote)).toBeNull();
    // The original is read in fullscreen only: the card offers no original toggle and reads nothing.
    expect(
      screen.queryByRole("button", { name: journalEn.showOriginal }),
    ).toBeNull();
    expect(host.call).not.toHaveBeenCalled();
  });

  it("shows no summary note in the meta line when the entry has no summary, and no Show original", () => {
    deliver({ entry: { ...created, summary: null } });

    expect(document.querySelector(".journal-card-links")?.textContent).toBe(
      "2 contacts · 1 task",
    );
    expect(screen.queryByText(journalEn.cardSummarized)).toBeNull();
    expect(screen.queryByText(journalEn.originalSavedNote)).toBeNull();
    expect(screen.queryByText(journalEn.summarizedNote)).toBeNull();
    expect(
      screen.queryByRole("button", { name: journalEn.showOriginal }),
    ).toBeNull();
  });

  it("shows no original line when the result carries no source", () => {
    deliver({ entry: { ...created, source_id: undefined } });

    expect(screen.queryByText(journalEn.originalSavedNote)).toBeNull();
    expect(screen.queryByText(journalEn.summarizedNote)).toBeNull();
    expect(
      screen.queryByRole("button", { name: journalEn.showOriginal }),
    ).toBeNull();
    expect(host.call).not.toHaveBeenCalled();
  });
});
