// A search with no match offers the way on: "+ Create contact "Zlatan"" creates it at once (the field opens only for a
// taken name or a failure), "Clear search" empties the search, a row shows archived matches, and "Tell Claude: ..." is
// as in the empty list. Simulated-host test (the Contacts room with a plain transport).
import { render, screen, waitFor } from "@testing-library/react";
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

const archivedZlatan = {
  id: "019f0000-0000-7000-8000-0000000000c9",
  display_name: "Zlatan Gammal",
  archived: true,
};

function host(
  options: {
    create?: boolean;
    /** The archived Contacts a search with "include archived" finds. */
    archived?: object[];
    /** The Contact the name check finds on its second read of the same search (a name taken meanwhile). */
    takenOnCheck?: object;
    /** create_contact answers with this failure. */
    createFails?: boolean;
  } = {},
) {
  let liveReads = 0;
  const call = vi.fn((name: string, args: object) => {
    if (name === "list_contacts") {
      const { q, include_archived: archived } = args as {
        q?: string | null;
        include_archived?: boolean;
      };
      if (q && archived) {
        return Promise.resolve({
          contacts: options.archived ?? [],
          next_cursor: null,
        });
      }
      if (q) liveReads += 1;
      return Promise.resolve({
        contacts: !q
          ? [anna]
          : liveReads > 1 && options.takenOnCheck
            ? [options.takenOnCheck]
            : [],
        next_cursor: null,
      });
    }
    if (name === "create_contact") {
      return options.createFails
        ? Promise.reject(new Error("offline"))
        : Promise.resolve({
            contact: {
              ...anna,
              id: "019f0000-0000-7000-8000-0000000000c2",
              display_name: (args as { display_name: string }).display_name,
              aliases: [],
              version: 1,
            },
          });
    }
    return Promise.reject(new Error(`unexpected ${name}`));
  });
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
    supportsTool: (name: string) =>
      name === "create_contact" ? options.create !== false : true,
  } as unknown as RoomProps["transport"];
  return Object.assign(transport, { calls: call });
}

/** Searches for a name nobody has and waits for the empty list's sentence. */
async function searchForNoMatch(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("Anna Andersson");
  await user.type(screen.getByRole("searchbox"), "Zlatan");
  await screen.findByText(
    "No contact matches “Zlatan”.",
    {},
    { timeout: 3000 },
  );
}

/** The create_contact calls a host has answered, with their arguments. */
const created = (transport: ReturnType<typeof host>) =>
  transport.calls.mock.calls
    .filter(([name]) => name === "create_contact")
    .map(([, args]) => args);

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("Contacts, search with no match", () => {
  it("offers Create contact with the query, which creates it at once, and the Claude hint", async () => {
    const user = userEvent.setup();
    const sendMessage = vi.fn().mockResolvedValue(true);
    const transport = host();
    render(
      <ContactsRoom
        mode="full"
        transport={transport}
        sendMessage={sendMessage}
      />,
    );
    await searchForNoMatch(user);
    expect(screen.getByText("Tell Claude:")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Save Zlatan as a contact/ }),
    );
    expect(sendMessage).toHaveBeenCalledWith("Save Zlatan as a contact");

    await user.click(
      screen.getByRole("button", { name: "Create contact “Zlatan”" }),
    );
    // No extra "Add": the Contact is created from the name already typed, under one key.
    await waitFor(() =>
      expect(created(transport)).toEqual([
        expect.objectContaining({ display_name: "Zlatan" }),
      ]),
    );
    expect(
      screen.queryByRole("textbox", { name: "New contact" }),
    ).not.toBeInTheDocument();
  });

  it("asks before creating when the name was taken meanwhile, and creates only after Create anyway", async () => {
    const user = userEvent.setup();
    const transport = host({
      takenOnCheck: { ...anna, display_name: "Zlatan" },
    });
    render(<ContactsRoom mode="full" transport={transport} />);
    await searchForNoMatch(user);
    await user.click(
      screen.getByRole("button", { name: "Create contact “Zlatan”" }),
    );
    expect(
      await screen.findByText("You already have a contact named “Zlatan”."),
    ).toBeInTheDocument();
    expect(created(transport)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Create anyway" }));
    await waitFor(() => expect(created(transport)).toHaveLength(1));
  });

  it("opens the field with the name and Try again when the create fails", async () => {
    const user = userEvent.setup();
    render(
      <ContactsRoom mode="full" transport={host({ createFails: true })} />,
    );
    await searchForNoMatch(user);
    await user.click(
      screen.getByRole("button", { name: "Create contact “Zlatan”" }),
    );
    expect(
      await screen.findByRole("textbox", { name: "New contact" }),
    ).toHaveValue("Zlatan");
    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeVisible();
  });

  it("offers Clear search, which empties the search and puts the focus back in it", async () => {
    const user = userEvent.setup();
    render(<ContactsRoom mode="full" transport={host()} />);
    await searchForNoMatch(user);
    await user.click(
      screen.getByRole("button", { name: contactsRoomLabelsEn.clearSearch }),
    );
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.getByRole("searchbox")).toHaveFocus();
    expect(await screen.findByText("Anna Andersson")).toBeInTheDocument();
  });

  it("shows how many archived Contacts match a search with no live hit, and Show turns on Show archived", async () => {
    const user = userEvent.setup();
    const transport = host({ archived: [archivedZlatan] });
    render(<ContactsRoom mode="full" transport={transport} />);
    await searchForNoMatch(user);
    await user.click(
      await screen.findByRole("button", {
        name: contactsRoomLabelsEn.showArchivedMatches(1),
      }),
    );
    expect(
      await screen.findByRole("button", { name: /Zlatan Gammal/ }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More options" }));
    expect(screen.getByRole("switch", { name: "Show archived" })).toBeChecked();
  });

  it("offers no archived row when no archived Contact matches", async () => {
    const user = userEvent.setup();
    render(<ContactsRoom mode="full" transport={host()} />);
    await searchForNoMatch(user);
    expect(
      screen.queryByRole("button", { name: /archived match/ }),
    ).not.toBeInTheDocument();
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
    expect(
      screen.getByText("Ask Claude in the Claude app:"),
    ).toBeInTheDocument();
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
