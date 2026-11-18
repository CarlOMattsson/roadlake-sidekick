// Creating a Contact whose name another Contact already has: the field says so first and offers Open or Create
// anyway; a name nobody has is created at once. Simulated-host test (the Contacts room with a plain transport).
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContactsRoom } from "@/features/work-app/contacts/contacts-room";
import { withSameName } from "@/features/work-app/contacts/new-contact-state";
import type { RoomProps } from "@/features/mcp-apps/room-types";

const anna = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  archived: false,
  role: "CEO",
  organization: "Acme AB",
};

function host() {
  const call = vi.fn((name: string, args: object) => {
    if (name === "list_contacts") {
      const q = (args as { q?: string | null }).q ?? "";
      return Promise.resolve({
        // The server also lists partial matches: "Anna" finds Anna Andersson without being her name.
        contacts: !q || q.toLowerCase().includes("anna") ? [anna] : [],
        next_cursor: null,
      });
    }
    if (name === "create_contact") {
      return Promise.resolve({
        contact: {
          ...anna,
          id: "019f0000-0000-7000-8000-0000000000c2",
          context_note: null,
          email: null,
          phone: null,
          aliases: [],
          created_at: "2026-11-18T09:00:00Z",
          updated_at: "2026-11-18T09:00:00Z",
          archived_at: null,
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
    supportsTool: () => true,
  } as unknown as RoomProps["transport"];
  return { call, transport };
}

const created = (call: ReturnType<typeof host>["call"]) =>
  call.mock.calls.filter(([name]) => name === "create_contact");

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("Contacts, a name that is taken", () => {
  it("warns before creating, and creates only after Create anyway", async () => {
    const user = userEvent.setup();
    const { call, transport } = host();
    render(<ContactsRoom mode="full" transport={transport} />);
    await screen.findByText("Anna Andersson");
    await user.click(screen.getByRole("button", { name: "New contact" }));
    await user.type(
      screen.getByRole("textbox", { name: "New contact" }),
      "anna   ANDERSSON{Enter}",
    );

    expect(
      await screen.findByText(
        "You already have a contact named “anna ANDERSSON”.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open Anna Andersson · CEO · Acme AB",
      }),
    ).toBeInTheDocument();
    expect(created(call)).toHaveLength(0);
    // The typed name stays in the field.
    expect(screen.getByRole("textbox", { name: "New contact" })).toHaveValue(
      "anna   ANDERSSON",
    );

    await user.click(screen.getByRole("button", { name: "Create anyway" }));
    await waitFor(() => expect(created(call)).toHaveLength(1));
  });

  it("creates a name nobody has without asking", async () => {
    const user = userEvent.setup();
    const { call, transport } = host();
    render(<ContactsRoom mode="full" transport={transport} />);
    await screen.findByText("Anna Andersson");
    await user.click(screen.getByRole("button", { name: "New contact" }));
    await user.type(
      screen.getByRole("textbox", { name: "New contact" }),
      "Anna{Enter}",
    );

    await waitFor(() => expect(created(call)).toHaveLength(1));
    expect(
      screen.queryByText(/already have a contact/),
    ).not.toBeInTheDocument();
  });

  it("compares names the way the server does", () => {
    const other = { ...anna, id: "other", display_name: "Anna Anderssen" };
    const archived = { ...anna, id: "old", archived: true };
    expect(
      withSameName("  anna   andersson ", [anna, other, archived]).map(
        (contact) => contact.id,
      ),
    ).toEqual([anna.id]);
  });
});
