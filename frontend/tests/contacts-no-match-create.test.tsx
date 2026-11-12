// A search with no match offers the way on: "+ Create contact "Zlatan"" opens the create field with the query in it,
// and "Tell Claude: ..." as in the empty list. Simulated-host test (the Contacts room with a plain transport).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import {
  contactsRoomLabelsEn,
  contactsRoomLabelsFor,
  contactsRoomLabelsSv,
} from "@/features/work-app/contacts/contacts-room-labels";
import type { RoomProps } from "@/features/mcp-apps/room-types";

const anna = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  archived: false,
};

function host(options: { create?: boolean } = {}) {
  const call = vi.fn((name: string, args: object) => {
    if (name === "list_contacts") {
      const q = (args as { q?: string | null }).q;
      return Promise.resolve({
        contacts: q ? [] : [anna],
        next_cursor: null,
      });
    }
    return Promise.reject(new Error(`unexpected ${name}`));
  });
  return {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
    supportsTool: (name: string) =>
      name === "create_contact" ? options.create !== false : true,
  } as unknown as RoomProps["transport"];
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("Contacts, search with no match", () => {
  it("offers Create contact with the query, which opens the create field prefilled, and the Claude hint", async () => {
    const user = userEvent.setup();
    const sendMessage = vi.fn().mockResolvedValue(true);
    render(
      <ContactsRoom mode="full" transport={host()} sendMessage={sendMessage} />,
    );
    await screen.findByText("Anna Andersson");
    await user.type(screen.getByRole("searchbox"), "Zlatan");
    expect(
      await screen.findByText(
        "No contact matches “Zlatan”.",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Tell Claude:")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Save Zlatan as a contact/ }),
    );
    expect(sendMessage).toHaveBeenCalledWith("Save Zlatan as a contact");

    await user.click(
      screen.getByRole("button", { name: "Create contact “Zlatan”" }),
    );
    const field = await screen.findByRole("textbox", { name: "New contact" });
    expect(field).toHaveValue("Zlatan");
    expect(field).toHaveFocus();
    // The search keeps its own text.
    expect(screen.getByRole("searchbox")).toHaveValue("Zlatan");
    // The plus of the field now creates.
    expect(
      within(field.closest(".sk-createfield")!).getByRole("button", {
        name: "Add",
      }),
    ).toBeInTheDocument();
  });

  it("offers no create row where the host has no create_contact, but still the Claude hint", async () => {
    const user = userEvent.setup();
    render(<ContactsRoom mode="full" transport={host({ create: false })} />);
    await screen.findByText("Anna Andersson");
    await user.type(screen.getByRole("searchbox"), "Zlatan");
    await waitFor(
      () =>
        expect(
          screen.getByText("No contact matches “Zlatan”."),
        ).toBeInTheDocument(),
      { timeout: 3000 },
    );
    expect(
      screen.queryByRole("button", { name: /Create contact/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Tell Claude:")).toBeInTheDocument();
  });

  it("has the new texts in both languages", () => {
    expect(contactsRoomLabelsFor("sv-SE")).toBe(contactsRoomLabelsSv);
    expect(contactsRoomLabelsSv.createNamed("Zlatan")).toBe(
      "Skapa kontakt ”Zlatan”",
    );
    expect(contactsRoomLabelsEn.createNamed("Zlatan")).toBe(
      "Create contact “Zlatan”",
    );
    expect(Object.keys(contactsRoomLabelsSv).sort()).toEqual(
      Object.keys(contactsRoomLabelsEn).sort(),
    );
  });
});
