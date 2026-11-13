import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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
import { preloadSidekickApp } from "./helpers/preload-sidekick-app";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// The entry view ("Linked" block) with the names of the entry's links, each chip with its remove button: this
// fullscreen view is where a link is removed. The bridge is the only thing mocked, as in the card tests.
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
const projectOffer = "019f0000-0000-7000-8000-0000000000p1";

const linked: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [],
  project_ids: [projectOffer],
  task_ids: ["019f0000-0000-7000-8000-0000000000t1"],
  contact_ids: [contactAnna, contactNoName],
  links: [
    { kind: "project", id: projectOffer, label: "Offert Norr" },
    { kind: "contact", id: contactAnna, label: "Anna Berg" },
    { kind: "contact", id: contactNoName, label: null },
  ],
  tags: [],
  archived: false,
  version: 2,
};

/** Delivers a tool result to every listener the app registered, as the host would. */
function deliver(structuredContent: unknown, isError = false) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

/**
 * Shows the entry view for one entry: the card for it is delivered first, so the entry view mounts and
 * reads the entry afresh; then the id-only result opens the view as the existing tests do.
 */
async function openEntryView(entry: JournalEntry) {
  host.call.mockImplementation((name: string) => {
    if (name === "get_journal_entry") return Promise.resolve({ entry });
    // The linked Task's title is read with get_task, so the entry shows the Task by name.
    if (name === "get_task")
      return Promise.resolve({ task: { title: "Skicka offert" } });
    return Promise.reject(new Error(`unexpected call ${name}`));
  });
  deliver({ entry: { ...entry, key_points: [] } });
  deliver({ entry: { id: entry.id } });
  await screen.findByRole("heading", { level: 3, name: "Linked" });
}

// The app's modules load at collection time, which has no timeout; the entry import in beforeAll then only
// runs the entry itself.
await preloadSidekickApp();

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
});

describe("journal entry view links", () => {
  it("lists the linked Projects and Contacts by name as chips in the Linked group, each with a remove button once the entry is being changed", async () => {
    await openEntryView(linked);

    // The chips are the entry's EntryLinks group, labelled as the Linked heading.
    const group = screen.getByRole("group", { name: "Linked" });
    expect(group).toHaveClass("journal-entry-links");
    expect(group.querySelectorAll(".journal-chip")).toHaveLength(3);
    expect(within(group).getByText("Offert Norr")).toBeInTheDocument();
    expect(within(group).getByText("Anna Berg")).toBeInTheDocument();
    // A contact without a name shows the contact fallback.
    expect(within(group).getByText("Contact")).toBeInTheDocument();
    // The view carries no × (a tap meant to open a Contact never lands on one); "Edit entry" brings them.
    expect(
      within(group).queryByRole("button", { name: /^Remove link to/ }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit entry" }));
    // Each chip has its own remove button, named after its link.
    for (const name of ["Offert Norr", "Anna Berg", "Contact"]) {
      expect(
        within(group).getByRole("button", { name: `Remove link to ${name}` }),
      ).toHaveClass("journal-chip-remove");
    }
    // Tasks are chips by title, in their own list outside the Linked group.
    const tasks = await screen.findByRole("list", { name: "Tasks" });
    expect(within(tasks).getByText("Skicka offert")).toBeInTheDocument();
    expect(within(group).queryByText("Skicka offert")).toBeNull();
    // The card's links line is not on the entry view.
    expect(document.querySelector(".journal-card-links")).toBeNull();
  });

  it("keeps the counts for an entry without links", async () => {
    await openEntryView({ ...linked, links: undefined });

    expect(screen.getByText("Projects: 1")).toBeInTheDocument();
    expect(screen.getByText("Contacts: 2")).toBeInTheDocument();
    expect(await screen.findByText("Skicka offert")).toBeInTheDocument();
    expect(
      document.querySelector(".journal-chips:not(.journal-task-chips)"),
    ).toBeNull();
  });

  it("hides the Linked block when the entry has no links and no tasks", async () => {
    host.call.mockImplementation((name: string) =>
      name === "get_journal_entry"
        ? Promise.resolve({
            entry: {
              ...linked,
              links: [],
              project_ids: [],
              task_ids: [],
              contact_ids: [],
            },
          })
        : Promise.reject(new Error(`unexpected call ${name}`)),
    );
    deliver({ entry: { ...linked, key_points: [] } });
    deliver({ entry: { id: entryId } });

    expect(
      await screen.findByRole("heading", { level: 2, name: linked.title }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: "Linked" }),
    ).not.toBeInTheDocument();
  });
});
