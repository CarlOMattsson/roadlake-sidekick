// The Journal entries under a Contact: a section with a button per entry when the host can open one,
// a calm line when the session may not read the journal, and nothing without the callback or entries.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoomProps } from "@/features/mcp-apps/room-types";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkContactRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};

const entryA = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  journal_date: "2026-11-03",
  title: "Möte om offerten",
};
const entryB = {
  id: "019f0000-0000-7000-8000-0000000000e2",
  journal_date: "2026-10-28",
  title: "Samtal med Anna",
};

/** A get_contact_context answer carrying the given journal part (or none at all). */
function contextWith(journal: unknown) {
  return {
    contact: anna,
    projects: { items: [], next_cursor: null },
    tasks: { items: [], next_cursor: null },
    journal_entries: journal,
  };
}

function workTransport(journal: unknown) {
  const getContactContext = vi.fn().mockResolvedValue(contextWith(journal));
  return {
    transport: { getContactContext } as unknown as WorkTransport,
    getContactContext,
  };
}

/** A Contact frame of the Work view; the Contact is read on mount through the transport. */
function renderContact(
  transport: WorkTransport,
  onOpenJournalEntry?: (entry: { id: string; title: string }) => void,
) {
  return render(
    <WorkView
      transport={transport}
      initial={{ kind: "contact", id: anna.id }}
      labels={workEn}
      onOpenJournalEntry={onOpenJournalEntry}
    />,
  );
}

describe("Journal entries under a Contact in the Work view", () => {
  it("lists the entries as buttons that call the callback with id and title", async () => {
    const { transport } = workTransport({
      items: [entryA, entryB],
      has_more: false,
      readable: true,
    });
    const onOpen = vi.fn();
    const user = userEvent.setup();
    const { container } = renderContact(transport, onOpen);

    expect(
      await screen.findByRole("heading", { name: workEn.journalEntries }),
    ).toBeInTheDocument();
    expect(
      container.querySelector('time[datetime="2026-11-03"]'),
    ).not.toBeNull();

    await user.click(screen.getByRole("button", { name: entryA.title }));
    expect(onOpen).toHaveBeenCalledWith({ id: entryA.id, title: entryA.title });
    expect(
      screen.getByRole("button", { name: entryB.title }),
    ).toBeInTheDocument();
  });

  it("draws a note row with no leading glyph: the title starts on the content edge", async () => {
    const { transport } = workTransport({
      items: [entryA, entryB],
      has_more: false,
      readable: true,
    });
    const { container } = renderContact(transport, vi.fn());

    await screen.findByRole("heading", { name: workEn.journalEntries });
    const rows = Array.from(
      container.querySelectorAll("li.work-open-row"),
    ).filter((row) => row.querySelector("time[datetime]"));
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.querySelector(".work-agenda-glyph")).toBeNull();
      // The only icon in the row is the shared › (no note icon).
      expect(row.querySelectorAll("svg")).toHaveLength(1);
      // One meta line (the date) under the title, and the shared › at the end.
      expect(row.querySelectorAll(".work-card-meta")).toHaveLength(1);
      expect(row.querySelector(".work-open-chevron")).not.toBeNull();
    }
  });

  it("shows a calm line without a button when the journal is not readable", async () => {
    const { transport } = workTransport({
      items: [],
      has_more: false,
      readable: false,
    });
    renderContact(transport, vi.fn());

    const line = await screen.findByText(workEn.journalUnavailable);
    expect(line.tagName).toBe("P");
    expect(line.closest("button")).toBeNull();
    expect(
      screen.getByRole("heading", { name: workEn.journalEntries }),
    ).toBeInTheDocument();
    expect(screen.queryByText(workEn.retry)).toBeNull();
  });

  it("draws no section without the callback, even when entries are linked", async () => {
    const { transport } = workTransport({
      items: [entryA],
      has_more: false,
      readable: true,
    });
    renderContact(transport);

    expect(
      await screen.findByRole("heading", { name: anna.display_name }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: workEn.journalEntries }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: entryA.title })).toBeNull();
  });

  it("draws no section when the readable list is empty", async () => {
    const { transport } = workTransport({
      items: [],
      has_more: false,
      readable: true,
    });
    renderContact(transport, vi.fn());

    expect(
      await screen.findByRole("heading", { name: anna.display_name }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: workEn.journalEntries }),
    ).toBeNull();
  });

  it("draws no section when the journal part is absent or malformed", async () => {
    const { transport } = workTransport({
      items: [{ id: entryA.id, journal_date: entryA.journal_date }],
      has_more: false,
      readable: true,
    });
    renderContact(transport, vi.fn());

    expect(
      await screen.findByRole("heading", { name: anna.display_name }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: workEn.journalEntries }),
    ).toBeNull();
  });

  it("shows at most ten entries", async () => {
    const items = Array.from({ length: 12 }, (_, i) => ({
      id: `019f0000-0000-7000-8000-0000000001${String(i).padStart(2, "0")}`,
      journal_date: "2026-11-01",
      title: `Anteckning ${i}`,
    }));
    const { transport } = workTransport({
      items,
      has_more: true,
      readable: true,
    });
    renderContact(transport, vi.fn());

    expect(
      await screen.findByRole("button", { name: "Anteckning 0" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Anteckning/ })).toHaveLength(
      10,
    );
  });

  it("uses the Swedish heading and calm line in Swedish", async () => {
    const { transport } = workTransport({
      items: [],
      has_more: false,
      readable: false,
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "contact", id: anna.id }}
        labels={workSv}
        onOpenJournalEntry={vi.fn()}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Anteckningar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Dagboken är inte tillgänglig för den här anslutningen"),
    ).toBeInTheDocument();
  });
});

describe("Journal entries under a Contact in the Contacts room", () => {
  /** A host that answers the Contact list and the Contact context with the given journal part. */
  function roomTransport(journal: unknown) {
    const call = vi.fn((name: string) => {
      if (name === "get_contact_context")
        return Promise.resolve(contextWith(journal));
      return Promise.reject(new Error(`unexpected ${name}`));
    });
    return {
      call,
      requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
      updateModelContext: vi.fn().mockResolvedValue(undefined),
    } as unknown as RoomProps["transport"];
  }

  const summary = {
    id: anna.id,
    display_name: anna.display_name,
    archived: false,
  };

  it("opens an entry through onNavigate to the journal entry view, with no label", async () => {
    const transport = roomTransport({
      items: [entryA],
      has_more: false,
      readable: true,
    });
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <ContactsRoom
        mode="full"
        transport={transport}
        resultId={1}
        initial={{ contacts: [summary], next_cursor: null }}
        onNavigate={onNavigate}
      />,
    );

    // With a host that routes, opening a Contact is a step on the shell's stack, not inside the room.
    await user.click(screen.getByRole("button", { name: /Anna Andersson/ }));
    expect(onNavigate).toHaveBeenCalledWith(
      expect.objectContaining({
        room: "contacts",
        view: "contact",
        id: anna.id,
      }),
    );
    onNavigate.mockClear();
    // The shell then draws that Contact in a room of its own, which this render stands in for.
    cleanup();
    render(
      <ContactsRoom
        mode="full"
        transport={transport}
        resultId={1}
        initial={{
          contact: anna,
          projects: { items: [], next_cursor: null },
          tasks: { items: [], next_cursor: null },
        }}
        onNavigate={onNavigate}
      />,
    );
    await user.click(await screen.findByRole("button", { name: entryA.title }));

    expect(onNavigate).toHaveBeenCalledWith({
      room: "journal",
      view: "entry",
      id: entryA.id,
    });
    expect(onNavigate.mock.calls[0]?.[0]).not.toHaveProperty("label");
  });

  it("shows no journal entries when the room has no onNavigate", async () => {
    const transport = roomTransport({
      items: [entryA],
      has_more: false,
      readable: true,
    });
    const user = userEvent.setup();
    render(
      <ContactsRoom
        mode="full"
        transport={transport}
        resultId={1}
        initial={{ contacts: [summary], next_cursor: null }}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Anna Andersson/ }));
    await waitFor(() =>
      expect(transport.call).toHaveBeenCalledWith(
        "get_contact_context",
        expect.anything(),
      ),
    );
    expect(
      await screen.findByRole("heading", { name: anna.display_name, level: 2 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: workSv.journalEntries }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: entryA.title })).toBeNull();
  });
});
