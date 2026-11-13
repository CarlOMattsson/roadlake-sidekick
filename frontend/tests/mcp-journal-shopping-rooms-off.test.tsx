import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { journalEn } from "@/features/journal-app/labels";
import { JournalRoom } from "@/features/journal-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { shoppingEn } from "@/features/shopping-app/labels";

// SIDEKICK_ENABLED_ROOMS: the backend names the rooms that are on in <meta name="sidekick-rooms">. With contacts and
// control off, the Journal and Shopping draw nothing that leads to them and make no contact call. No meta: all on.

const LIST_ID = "019f0000-0000-7000-8000-0000000000b1";
const ITEM_ID = "019f0000-0000-7000-8000-0000000000c1";
const CONTACT_ID = "019f0000-0000-7000-8000-0000000000e1";
const ENTRY_ID = "019f0000-0000-7000-8000-0000000000d1";
const LOCALE = '<meta name="sidekick-app-locale" content="en">';
const ROOMS_OFF =
  '<meta name="sidekick-rooms" content="work,journal,shopping">';

const LIST = {
  id: LIST_ID,
  name: "Veckohandel",
  version: 1,
  archived: false,
  created_at: "2026-11-01T12:00:00Z",
  updated_at: "2026-11-01T12:00:00Z",
};

const ITEM = {
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
  recipient_contact_id: null,
  store: null,
  target_date: null,
  created_at: "2026-11-01T12:00:00Z",
  updated_at: "2026-11-01T12:00:00Z",
  version: 1,
};

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

const DAY = {
  journal_date: "2026-11-09",
  entries: [ENTRY],
  summary: { status: "none" },
};

function transportOf(answer: (name: string) => unknown) {
  const call = vi.fn((name: string) => Promise.resolve(answer(name)));
  const transport: RoomTransport = {
    call: call as unknown as RoomTransport["call"],
    requestDisplayMode: () => Promise.resolve("fullscreen"),
    updateModelContext: () => Promise.resolve(),
  };
  return { call, transport };
}

/** Declares the rooms of the instance, or none (a host that does not declare them). */
function declareRooms(rooms?: string) {
  document.head.innerHTML = LOCALE + (rooms ?? "");
}

function called(call: ReturnType<typeof transportOf>["call"]): string[] {
  return call.mock.calls.map(([name]) => name);
}

afterEach(() => {
  cleanup();
  document.head.innerHTML = "";
});

describe("Shopping with the Contact and Control rooms off", () => {
  function shopping() {
    return transportOf((name) => {
      if (name === "list_shopping_lists")
        return { lists: [LIST], next_offset: null };
      if (name === "get_shopping_list")
        return {
          shopping_list: LIST,
          evaluated_on: "2026-11-09",
          next_offset: null,
          items: [ITEM],
        };
      return { contacts: [] };
    });
  }

  async function openEditor() {
    const user = userEvent.setup();
    await user.click(await screen.findByText("Blommor"));
    await screen.findByText(/^Edit: Blommor/);
    // The recipient fields wait behind "More fields" until the form is opened further.
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
  }

  it("keeps the recipient search when every room is on", async () => {
    declareRooms();
    const { transport } = shopping();
    render(<ShoppingRoom mode="full" transport={transport} />);
    await openEditor();

    expect(screen.getByLabelText("Contact name")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Find contact" }),
    ).toBeInTheDocument();
  });

  it("has no recipient search and no contact call when contacts is off", async () => {
    declareRooms(ROOMS_OFF);
    const { call, transport } = shopping();
    render(<ShoppingRoom mode="full" transport={transport} />);
    await openEditor();

    expect(screen.queryByLabelText("Contact name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Find contact" })).toBeNull();
    expect(screen.queryByLabelText("Gift recipient (optional)")).toBeNull();
    expect(called(call)).not.toContain("list_contacts");
  });

  async function menuEntries() {
    const user = userEvent.setup();
    await screen.findByText("Blommor");
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moreActions }),
    );
    return screen.getAllByRole("button").map((button) => button.textContent);
  }

  it("ends the ⋯ menu with Control when every room is on", async () => {
    declareRooms();
    const { transport } = shopping();
    render(
      <ShoppingRoom mode="full" transport={transport} onNavigate={vi.fn()} />,
    );

    expect(await menuEntries()).toContain("Memory and control");
  });

  it("leaves Control out of the ⋯ menu when control is off", async () => {
    declareRooms(ROOMS_OFF);
    const { transport } = shopping();
    render(
      <ShoppingRoom mode="full" transport={transport} onNavigate={vi.fn()} />,
    );

    const entries = await menuEntries();
    expect(entries).toContain(shoppingEn.editList);
    expect(entries).not.toContain("Memory and control");
  });
});

describe("Journal with the Contact and Control rooms off", () => {
  function journal() {
    return transportOf((name) => {
      if (name === "get_journal_entry") return { entry: ENTRY };
      if (name === "list_tags") return { tags: [] };
      throw new Error(`unexpected ${name}`);
    });
  }

  function renderEntry() {
    const { call, transport } = journal();
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: ENTRY_ID } }}
        onNavigate={vi.fn()}
      />,
    );
    return call;
  }

  it("draws the contact as a button with a remove control when every room is on", async () => {
    declareRooms();
    renderEntry();

    expect(
      await screen.findByRole("button", { name: "Anna" }),
    ).toBeInTheDocument();
    // The remove control shows only while the entry is being changed, not in the view.
    expect(
      screen.queryByRole("button", { name: journalEn.linkRemove("Anna") }),
    ).toBeNull();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: journalEn.editEntry }));
    expect(
      screen.getByRole("button", { name: journalEn.linkRemove("Anna") }),
    ).toBeInTheDocument();
  });

  it("shows the contact as plain text, with no remove control, when contacts is off", async () => {
    declareRooms(ROOMS_OFF);
    const call = renderEntry();

    expect(await screen.findByText("Måndag")).toBeInTheDocument();
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anna" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: journalEn.linkRemove("Anna") }),
    ).toBeNull();
    // The entry and the tag vocabulary for its tag field; nothing about the Contact room.
    expect([...called(call)].sort()).toEqual([
      "get_journal_entry",
      "list_tags",
    ]);
  });

  async function dayMenu() {
    const user = userEvent.setup();
    const { transport } = transportOf((name) =>
      name === "list_tags" ? { tags: [] } : DAY,
    );
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={DAY}
        onNavigate={vi.fn()}
      />,
    );
    const more = screen.queryByRole("button", { name: journalEn.moreActions });
    if (more) await user.click(more);
    return more;
  }

  it("has the Control entry in the day's ⋯ when every room is on", async () => {
    declareRooms();
    await dayMenu();

    expect(
      screen.getByRole("button", { name: "Memory and control" }),
    ).toBeInTheDocument();
  });

  it("has no Control entry, and no ⋯, when control is off", async () => {
    declareRooms(ROOMS_OFF);
    const more = await dayMenu();

    expect(more).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Memory and control" }),
    ).toBeNull();
  });
});
