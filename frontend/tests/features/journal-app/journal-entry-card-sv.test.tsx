import { act, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { JournalEntry } from "@/features/journal-app/transport";
import { preloadSidekickApp } from "@tests/helpers/preload-sidekick-app";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// Swedish counterpart of journal-entry-card.test.tsx. The app reads its language once, when
// sidekick-entry is imported, so the Swedish Sidekick setting needs its own test file and import.
// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
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
    onHostContext: () => undefined,
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

/** Delivers a tool result to every listener the app registered, as the host would. */
function deliver(structuredContent: unknown, isError = false) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

// The app's modules load at collection time, which has no timeout; the entry import in beforeAll then only
// runs the entry itself.
await preloadSidekickApp();

afterAll(() => {
  document.head.innerHTML = "";
  vi.useRealTimers();
});

beforeAll(async () => {
  // Today is pinned (the Date only, timers stay real), so "idag" and the year rule are fixed.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-03T12:00:00"));
  // The Sidekick setting is declared explicitly; the host's en-GB locale must not change it.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="sv">';
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

describe("journal entry card in Swedish", () => {
  it("shows the card in Swedish, whatever the host locale", () => {
    deliver({ entry: created });

    expect(
      screen.getByRole("heading", { level: 1, name: "Dagbok" }),
    ).toHaveClass("sk-eyebrow");
    expect(
      screen.getByRole("button", { name: "Öppna anteckningen" }),
    ).toHaveClass("sk-btn--open");
    expect(document.querySelector("p.journal-card-links")?.textContent).toBe(
      "Sammanfattad av Claude · 2 kontakter · 1 uppgift",
    );
  });

  it("names the day and time in Swedish without sparad and without kl.", () => {
    deliver({ entry: { ...created, occurred_at: "2026-10-24T14:05:00" } });
    expect(screen.getByText("24 okt 14:05")).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent(/sparad/);
  });

  it("says idag with the time for an entry from today", () => {
    deliver({
      entry: {
        ...created,
        journal_date: "2026-11-03",
        occurred_at: "2026-11-03T12:30:00",
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^idag 12:30$/);
  });

  it("says igår with the time for an entry from yesterday", () => {
    deliver({
      entry: {
        ...created,
        journal_date: "2026-11-02",
        occurred_at: "2026-11-02T18:05:00",
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^igår 18:05$/);
  });

  it("says idag for an entry from today without a time", () => {
    deliver({
      entry: { ...created, journal_date: "2026-11-03", occurred_at: null },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^idag$/);
  });

  it("says only sparad when the result carries no journal date", () => {
    deliver({
      entry: { ...created, journal_date: undefined, occurred_at: null },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^sparad$/);
  });

  it("shows Sammanfattad av Claude in the Swedish meta line, not the saved note, and no Visa originaltext in the card", () => {
    deliver({ entry: created });
    expect(screen.getByText("Sammanfattad av Claude").closest("p")).toHaveClass(
      "sk-card__meta",
      "journal-card-links",
    );
    expect(
      screen.queryByText("Din originaltext är sparad"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Visa originaltext" }),
    ).not.toBeInTheDocument();
  });

  it("names the links in one Swedish line: A och B, A, B och C, and A, B, C och 1 fler («fler», not «till»)", () => {
    deliver({
      entry: {
        ...created,
        task_ids: [],
        links: [
          { kind: "contact", id: "c1", label: "Anna Berg" },
          { kind: "project", id: "p1", label: "Köket" },
        ],
      },
    });
    expect(document.querySelector("p.journal-card-links")?.textContent).toBe(
      "Sammanfattad av Claude · Kopplad till Anna Berg och Köket",
    );

    deliver({
      entry: {
        ...created,
        task_ids: [],
        links: [
          { kind: "contact", id: "c1", label: "Anna Berg" },
          { kind: "project", id: "p1", label: "Köket" },
          { kind: "contact", id: "c2", label: null },
          { kind: "contact", id: "c3", label: "Lars Ek" },
        ],
      },
    });
    expect(document.querySelector("p.journal-card-links")?.textContent).toBe(
      "Sammanfattad av Claude · Kopplad till Anna Berg, Köket, Kontakt och 1 fler",
    );
  });

  it("says the entry has one task in the same line as its links", () => {
    deliver({
      entry: {
        ...created,
        task_ids: ["019f0000-0000-7000-8000-0000000000t1"],
        links: [{ kind: "contact", id: "c1", label: "Anna Berg" }],
      },
    });
    expect(document.querySelector("p.journal-card-links")?.textContent).toBe(
      "Sammanfattad av Claude · Kopplad till Anna Berg · 1 uppgift",
    );
  });
});
