// The Contacts room on its own: list, search, one Contact and Back, all through the room transport.
// Mounted without a result it reads the list for itself; with a list_contacts result it shows that page.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workSv } from "@/features/work-app/shared/labels";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import type { RoomProps } from "@/features/mcp-apps/room-types";

const anna = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  archived: false,
};
const bo = {
  id: "019f0000-0000-7000-8000-0000000000c2",
  display_name: "Bo Berg",
  archived: false,
};

function contactRecord(summary: typeof anna) {
  return {
    ...summary,
    email: null,
    phone: null,
    context_note: null,
    relationship: null,
    organization: null,
    role: null,
    address: null,
    aliases: [],
    archived_at: null,
    version: 1,
  };
}

/** A host that answers the two reads the room makes. */
function host() {
  const call = vi.fn((name: string, args: object) => {
    if (name === "list_contacts") {
      const q = (args as { q?: string | null }).q;
      const all = [anna, bo];
      const contacts = q ? all.filter((c) => c.display_name.includes(q)) : all;
      return Promise.resolve({ contacts, next_cursor: null });
    }
    if (name === "get_contact_context") {
      return Promise.resolve({
        contact: contactRecord(anna),
        projects: { items: [], next_cursor: null },
        tasks: { items: [], next_cursor: null },
      });
    }
    return Promise.reject(new Error(`unexpected ${name}`));
  });
  return {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomProps["transport"] & { call: typeof call };
}

describe("ContactsRoom", () => {
  it("reads the list for itself when mounted without a result, and opens a Contact and goes back", async () => {
    const transport = host();
    render(<ContactsRoom mode="full" transport={transport} />);

    expect(await screen.findByText("Anna Andersson")).toBeInTheDocument();
    expect(screen.getByText("Bo Berg")).toBeInTheDocument();
    expect(transport.call).toHaveBeenCalledWith(
      "list_contacts",
      expect.objectContaining({ include_archived: false }),
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Anna Andersson/ }));
    await waitFor(() =>
      expect(transport.call).toHaveBeenCalledWith(
        "get_contact_context",
        expect.objectContaining({ contact_id: anna.id }),
      ),
    );
    await user.click(
      await screen.findByRole("button", {
        name: `Tillbaka till ${workSv.contacts}`,
      }),
    );
    expect(await screen.findByText("Bo Berg")).toBeInTheDocument();
  });

  it("searches through the transport", async () => {
    const transport = host();
    render(<ContactsRoom mode="full" transport={transport} />);
    await screen.findByText("Bo Berg");

    const user = userEvent.setup();
    await user.type(screen.getByRole("searchbox"), "Bo");
    await waitFor(() =>
      expect(screen.queryByText("Anna Andersson")).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("Bo Berg")).toBeInTheDocument();
  });

  it("shows the page a list_contacts result carried, without reading again", async () => {
    const transport = host();
    render(
      <ContactsRoom
        mode="full"
        transport={transport}
        resultId={1}
        initial={{ contacts: [bo], next_cursor: null }}
      />,
    );
    expect(await screen.findByText("Bo Berg")).toBeInTheDocument();
    expect(screen.queryByText("Anna Andersson")).not.toBeInTheDocument();
    // Only the tag vocabulary for the filter row is read; the list itself is not.
    expect(vi.mocked(transport.call).mock.calls.map(([name]) => name)).toEqual([
      "list_tags",
    ]);
  });

  it("ignores a result that belongs to another room", async () => {
    const transport = host();
    const { rerender } = render(
      <ContactsRoom
        mode="full"
        transport={transport}
        resultId={1}
        initial={{ contacts: [bo], next_cursor: null }}
      />,
    );
    await screen.findByText("Bo Berg");
    rerender(
      <ContactsRoom
        mode="full"
        transport={transport}
        resultId={2}
        initial={{ columns: { todo: [] } }}
      />,
    );
    expect(screen.getByText("Bo Berg")).toBeInTheDocument();
  });
});
