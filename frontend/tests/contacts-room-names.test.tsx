// The Contacts room is Kontakter (Contacts) everywhere: its inline summary eyebrow and the region the
// view draws say the room's name, not the Work app's "Arbete". Inside the Sidekick shell's frame the
// room's region is named by the room too, so no region in the room is called Arbete.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import type { RoomProps } from "@/features/mcp-apps/room-types";
import { workSv } from "@/features/work-app/shared/labels";
import {
  ContactsRoom,
  contactsRoomNames,
} from "@/features/work-app/contacts/contacts-room";

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

/** A host that answers the reads the room makes. */
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

/** Declares the app locale the way the host page does (meta sidekick-app-locale). */
function declareLocale(locale: "sv" | "en") {
  const meta = document.createElement("meta");
  meta.name = "sidekick-app-locale";
  meta.content = locale;
  document.head.append(meta);
  return () => meta.remove();
}

let undeclare: (() => void) | undefined;

afterEach(() => {
  undeclare?.();
  undeclare = undefined;
});

describe("contactsRoomNames", () => {
  it("names the room Kontakter in Swedish and Contacts in English", () => {
    const sv = contactsRoomNames("sv");
    expect([
      sv.labels.title,
      sv.inlineLabels.appName,
      sv.cardLabels.appName,
    ]).toEqual(["Kontakter", "Kontakter", "Kontakter"]);

    const en = contactsRoomNames("en");
    expect([
      en.labels.title,
      en.inlineLabels.appName,
      en.cardLabels.appName,
    ]).toEqual(["Contacts", "Contacts", "Contacts"]);
  });
});

describe("ContactsRoom names", () => {
  it("the inline list card has the eyebrow Kontakter and no Arbete", () => {
    const transport = host();
    const { container } = render(
      <ContactsRoom
        mode="inline"
        fullscreenAvailable
        transport={transport}
        resultId={1}
        initial={{ contacts: [anna, bo], next_cursor: null }}
      />,
    );

    expect(container.querySelector(".sk-eyebrow")?.textContent).toBe(
      "Kontakter",
    );
    expect(screen.queryByText("Arbete")).toBeNull();
    expect(screen.queryByRole("region", { name: "Arbete" })).toBeNull();
  });

  it("the inline list card is Contacts in English", () => {
    undeclare = declareLocale("en");
    const transport = host();
    const { container } = render(
      <ContactsRoom
        mode="inline"
        fullscreenAvailable
        transport={transport}
        resultId={1}
        initial={{ contacts: [anna, bo], next_cursor: null }}
      />,
    );

    expect(container.querySelector(".sk-eyebrow")?.textContent).toBe(
      "Contacts",
    );
    expect(screen.queryByText("Work")).toBeNull();
    expect(screen.queryByRole("region", { name: "Work" })).toBeNull();
  });

  it("inside the shell's frame, a Contact is still in the Kontakter region and none is Arbete", async () => {
    const transport = host();
    render(
      <RoomSurfaceContext.Provider value={{ active: true, framed: true }}>
        <ContactsRoom mode="full" transport={transport} />
      </RoomSurfaceContext.Provider>,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: /Anna Andersson/ }),
    );
    await screen.findByRole("button", {
      name: `Tillbaka till ${workSv.contacts}`,
    });

    expect(screen.queryByRole("region", { name: "Arbete" })).toBeNull();
    expect(
      screen.getAllByRole("region", { name: "Kontakter" }).length,
    ).toBeGreaterThan(0);
  });
});
