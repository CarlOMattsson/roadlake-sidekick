import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { JournalRoom } from "@/features/journal-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";

// The rooms leave out what the host cannot answer, by asking the transport (`toolOffered`). A host without a tool list
// (Claude) keeps every control. The mobile app's list lacks list_contacts and the Journal's draft tools; it has the original text (get_journal_source).

const LIST_ID = "019f0000-0000-7000-8000-0000000000b1";
const ITEM_ID = "019f0000-0000-7000-8000-0000000000c1";
const CONTACT_ID = "019f0000-0000-7000-8000-0000000000e1";
const ENTRY_ID = "019f0000-0000-7000-8000-0000000000d1";

const LIST = {
  id: LIST_ID,
  name: "Veckohandel",
  version: 1,
  archived: false,
  created_at: "2026-11-01T12:00:00Z",
  updated_at: "2026-11-01T12:00:00Z",
};

function shoppingItem(recipient: string | null) {
  return {
    id: ITEM_ID,
    list_id: LIST_ID,
    name: "Blommor",
    quantity: "1",
    unit: null,
    note: null,
    occasion: null,
    offer: null,
    offer_status: "none",
    product_url: null,
    purchased: false,
    purchased_at: null,
    recipient_contact_id: recipient,
    store: null,
    target_date: null,
    created_at: "2026-11-01T12:00:00Z",
    updated_at: "2026-11-01T12:00:00Z",
    version: 1,
  };
}

const ENTRY = {
  id: ENTRY_ID,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-11-09",
  occurred_at: null,
  title: "Måndag",
  summary: "En dag.",
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [CONTACT_ID],
  links: [{ kind: "contact", id: CONTACT_ID, label: "Anna" }],
  archived: false,
  version: 1,
};

function transportOf(
  answer: (name: string) => unknown,
  supportsTool?: (name: string) => boolean,
) {
  const call = vi.fn((name: string) => Promise.resolve(answer(name)));
  const transport: RoomTransport = {
    call: call as unknown as RoomTransport["call"],
    requestDisplayMode: () => Promise.resolve("fullscreen"),
    updateModelContext: () => Promise.resolve(),
    ...(supportsTool ? { supportsTool } : {}),
  };
  return { call, transport };
}

const COMPANION_LIKE = (name: string) =>
  ![
    "list_contacts",
    "list_pending_journal",
    "get_contact_context",
    "list_tags",
  ].includes(name);

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterAll(() => {
  document.head.innerHTML = "";
});
afterEach(cleanup);

describe("Shopping: the recipient search", () => {
  function shopping(
    recipient: string | null,
    supports?: typeof COMPANION_LIKE,
  ) {
    return transportOf((name) => {
      if (name === "list_shopping_lists")
        return { lists: [LIST], next_offset: null };
      if (name === "get_shopping_list")
        return {
          shopping_list: LIST,
          evaluated_on: "2026-11-09",
          next_offset: null,
          items: [shoppingItem(recipient)],
        };
      return { contacts: [] };
    }, supports);
  }

  async function openEditor() {
    const user = userEvent.setup();
    await user.click(await screen.findByText("Blommor"));
    await screen.findByText(/^Edit: Blommor/);
    // The recipient fields wait behind "More fields" until the form is opened further.
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
  }

  it("keeps the search where the host answers list_contacts (Claude)", async () => {
    const { transport } = shopping(null);
    render(<ShoppingRoom mode="full" transport={transport} />);
    await openEditor();

    expect(screen.getByLabelText("Contact name")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Find contact" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Gift recipient (optional)"),
    ).toBeInTheDocument();
  });

  it("offers no recipient field and no search in the app for an item without a recipient", async () => {
    const { call, transport } = shopping(null, COMPANION_LIKE);
    render(<ShoppingRoom mode="full" transport={transport} />);
    await openEditor();

    expect(screen.queryByLabelText("Contact name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Find contact" })).toBeNull();
    expect(screen.queryByLabelText("Gift recipient (optional)")).toBeNull();
    expect(call.mock.calls.map(([name]) => name)).not.toContain(
      "list_contacts",
    );
  });

  it("keeps the recipient an item already has, without a search", async () => {
    const { call, transport } = shopping(CONTACT_ID, COMPANION_LIKE);
    render(<ShoppingRoom mode="full" transport={transport} />);
    await openEditor();

    expect(screen.getByLabelText("Gift recipient (optional)")).toHaveValue(
      CONTACT_ID,
    );
    expect(screen.getByText("Current recipient")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Find contact" })).toBeNull();
    expect(call.mock.calls.map(([name]) => name)).not.toContain(
      "list_contacts",
    );
  });
});

describe("Journal: originals, drafts and the contact room", () => {
  function journal(supports?: typeof COMPANION_LIKE) {
    return transportOf((name) => {
      if (name === "get_journal_entry") return { entry: ENTRY };
      if (name === "list_tags") return { tags: [] };
      throw new Error(`unexpected ${name}`);
    }, supports);
  }

  it("shows the original and the contact link on a host without a tool list (Claude)", async () => {
    const { transport } = journal();
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: ENTRY_ID } }}
        onNavigate={() => undefined}
      />,
    );

    expect(
      await screen.findByRole("button", { name: "Show original" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anna" })).toBeInTheDocument();
  });

  it("keeps the original and leaves out the contact link in the app, and reads nothing it cannot", async () => {
    const { call, transport } = journal(COMPANION_LIKE);
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: ENTRY_ID } }}
        onNavigate={() => undefined}
      />,
    );

    expect(await screen.findByText("Måndag")).toBeInTheDocument();
    // The words of a hand-written entry live in the original, which the app can read.
    expect(
      screen.getByRole("button", { name: "Show original" }),
    ).toBeInTheDocument();
    // The contact stays as a name (the contact room is not in the app).
    expect(screen.queryByRole("button", { name: "Anna" })).toBeNull();
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(call.mock.calls.map(([name]) => name)).toEqual([
      "get_journal_entry",
    ]);
  });
});
