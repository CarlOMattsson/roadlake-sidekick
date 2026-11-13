import { act, screen, waitFor } from "@testing-library/react";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { JournalEntry } from "@/features/journal-app/transport";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// The card's links: one muted line of text with the names. No chips and no remove button here: a link is
// removed in the entry's fullscreen view (journal-entry-unlink.test.tsx). The bridge is the only thing mocked:
// sidekick-entry runs at import time and binds its listeners here.
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
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: () => undefined,
    onTeardown: () => undefined,
  }),
}));

const entryId = "019f0000-0000-7000-8000-0000000000e1";
const contactAnna = "019f0000-0000-7000-8000-0000000000c1";
const contactNoName = "019f0000-0000-7000-8000-0000000000c2";
const contactLars = "019f0000-0000-7000-8000-0000000000c3";
const projectOffer = "019f0000-0000-7000-8000-0000000000p1";
const projectOffice = "019f0000-0000-7000-8000-0000000000p2";

const created: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
  project_ids: [projectOffer, projectOffice],
  task_ids: ["019f0000-0000-7000-8000-0000000000t1"],
  contact_ids: [contactAnna, contactNoName, contactLars],
  links: [
    { kind: "contact", id: contactAnna, label: "Anna Berg" },
    { kind: "project", id: projectOffer, label: "Offert Norr" },
    { kind: "contact", id: contactNoName, label: null },
    { kind: "contact", id: contactLars, label: "Lars Ek" },
    { kind: "project", id: projectOffice, label: "Kontor" },
  ],
  tags: [],
  archived: false,
  version: 3,
};

/** Delivers a tool result to every listener the app registered, as the host would. */
function deliver(structuredContent: unknown, isError = false) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

/** The card's one muted meta line as text (summary note, links, tasks), or null when the card shows none. */
function metaLine(): string | null {
  return document.querySelector("p.journal-card-links")?.textContent ?? null;
}

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    availableDisplayModes: ["inline", "fullscreen"],
  });
  await import("@/features/mcp-apps/sidekick-entry");
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
      : Promise.reject(new Error(`unexpected call ${name}`)),
  );
  host.requestDisplayMode.mockReset();
  host.requestDisplayMode.mockResolvedValue("inline");
});

describe("journal entry card links", () => {
  it("names the first three links in one line of text and counts the rest, with the task count after a dot", () => {
    deliver({ entry: created });

    expect(metaLine()).toBe(
      "Summarized by Claude · Linked to Anna Berg, Offert Norr, Contact and 2 more · 1 task",
    );
    // A contact's name is a text button that opens the contact; a project's name is plain text.
    expect(screen.getByRole("button", { name: "Anna Berg" })).toHaveClass(
      "journal-link-name",
    );
    expect(screen.getByText("Offert Norr").tagName).toBe("SPAN");
    expect(screen.queryByText("Lars Ek")).not.toBeInTheDocument();
    // No chips and no remove buttons on the card.
    expect(document.querySelector(".journal-chips")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Remove link/ }),
    ).not.toBeInTheDocument();
    expect(host.call).not.toHaveBeenCalled();
  });

  it("lists two links with 'and' and no count", () => {
    deliver({
      entry: { ...created, links: created.links?.slice(0, 2), task_ids: [] },
    });

    expect(metaLine()).toBe(
      "Summarized by Claude · Linked to Anna Berg and Offert Norr",
    );
  });

  it("lists three links with commas and 'and', with no count of the rest", () => {
    deliver({
      entry: { ...created, links: created.links?.slice(0, 3), task_ids: [] },
    });

    expect(metaLine()).toBe(
      "Summarized by Claude · Linked to Anna Berg, Offert Norr and Contact",
    );
  });

  it("shows the project fallback when a project has no name", () => {
    deliver({
      entry: {
        ...created,
        links: [{ kind: "project", id: projectOffer, label: null }],
        task_ids: [],
      },
    });

    expect(metaLine()).toBe("Summarized by Claude · Linked to Project");
    expect(screen.getByText("Project")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Remove link/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps the count line for a result without links", () => {
    deliver({ entry: { ...created, links: undefined } });

    expect(metaLine()).toBe("Summarized by Claude · 3 contacts · 1 task");
    expect(document.querySelector(".journal-chips")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Remove link/ }),
    ).not.toBeInTheDocument();
  });

  it("says plainly when there are no links and no tasks", () => {
    deliver({ entry: { ...created, links: [], task_ids: [] } });

    expect(metaLine()).toBe(
      "Summarized by Claude · Not linked to anything yet",
    );
  });

  it("shows only the task count when the entry has tasks but no links", () => {
    deliver({ entry: { ...created, links: [] } });

    expect(metaLine()).toBe("Summarized by Claude · 1 task");
    expect(metaLine()).not.toContain("Not linked to anything yet");
  });

  it("shows the names without remove buttons when the result has no version", async () => {
    deliver({ entry: { ...created, version: undefined } });

    expect(await screen.findByText("Anna Berg")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Remove link/ }),
    ).not.toBeInTheDocument();
    expect(host.call).not.toHaveBeenCalled();
  });
});
