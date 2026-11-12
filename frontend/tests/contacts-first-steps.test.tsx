// The Contacts room's first steps: the empty list says what to tell Claude, a
// Contact with only its name offers its first fields and a sentence for Claude, and a failed first result can be read
// again from the room's own error notice.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import {
  contactsRoomLabelsEn,
  contactsRoomLabelsSv,
} from "@/features/work-app/contacts/contacts-room-labels";
import type { RoomProps } from "@/features/mcp-apps/room-types";

const gustav = {
  id: "019f0000-0000-7000-8000-0000000000c9",
  display_name: "Gustav Lund",
  archived: false,
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

function host(contacts: unknown[] = []) {
  const call = vi.fn((name: string) => {
    if (name === "list_contacts")
      return Promise.resolve({ contacts, next_cursor: null });
    if (name === "get_contact_context")
      return Promise.resolve({
        contact: gustav,
        projects: { items: [], next_cursor: null },
        tasks: { items: [], next_cursor: null },
      });
    return Promise.reject(new Error(`unexpected ${name}`));
  });
  return {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomProps["transport"] & { call: typeof call };
}

const t = contactsRoomLabelsSv;

describe("the Contacts room's first steps", () => {
  it("has the same words in Swedish and English", () => {
    expect(Object.keys(contactsRoomLabelsEn).sort()).toEqual(
      Object.keys(contactsRoomLabelsSv).sort(),
    );
  });

  it("teaches what to tell Claude on an empty list, and sends the example", async () => {
    const sendMessage = vi.fn().mockResolvedValue(true);
    render(
      <ContactsRoom mode="full" transport={host()} sendMessage={sendMessage} />,
    );
    expect(await screen.findByText(t.emptyHint)).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: new RegExp(t.emptyAsk) }));
    expect(sendMessage).toHaveBeenCalledWith(t.emptyAsk);
  });

  it("shows the example as text when the host takes no messages", async () => {
    render(<ContactsRoom mode="full" transport={host()} />);
    expect(await screen.findByText(`”${t.emptyAsk}”`)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: new RegExp(t.emptyAsk) }),
    ).toBeNull();
  });

  it("gives a Contact with only its name its first steps, which open the editor on that field", async () => {
    const sendMessage = vi.fn().mockResolvedValue(true);
    const user = userEvent.setup();
    render(
      <ContactsRoom
        mode="full"
        transport={host([gustav])}
        sendMessage={sendMessage}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: /Gustav Lund/ }),
    );
    expect(await screen.findByText(t.bareTitle("Gustav"))).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: new RegExp(t.bareAsk("Gustav Lund")),
      }),
    );
    expect(sendMessage).toHaveBeenCalledWith(t.bareAsk("Gustav Lund"));

    await user.click(screen.getByRole("button", { name: t.addPhoneLabel }));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByLabelText(/Telefon/)),
    );
    // While the editor is open the first steps are gone: one way to fill in at a time.
    expect(screen.queryByText(t.bareTitle("Gustav"))).toBeNull();
  });

  it("reads the list again from the error of a failed first result", async () => {
    const transport = host([gustav]);
    render(
      <ContactsRoom
        mode="full"
        transport={transport}
        initial={{ code: "unavailable" }}
        initialError
        resultId={1}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Kontakterna kunde inte hämtas",
    );
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Gustav Lund")).toBeInTheDocument();
    expect(transport.call).toHaveBeenCalledWith(
      "list_contacts",
      expect.anything(),
    );
  });
});
