import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import { hierarchyDetailLabelsFor } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { type WorkContactRecord } from "@/features/work-app/transport/transport";
import {
  KEY,
  anna,
  annaTasks,
  contactRoot,
  keyOf,
  openEdit,
  openMoreMenu,
  projectA,
  transport,
} from "@tests/helpers/work-app-fixtures";

const aliasId = "019f0000-0000-7000-8000-0000000000f1";

const alias = {
  id: aliasId,
  value: "Annan A",
  created_at: "2026-10-25T10:00:00Z",
};

/** A get_contact_context answer with the given Contact and no Projects or Tasks. */
function contextOf(contact: WorkContactRecord) {
  return Promise.resolve({
    contact,
    projects: { items: [], next_cursor: null },
    tasks: { items: [], next_cursor: null },
  });
}

it("shows the Contact's note under 'About Anna' and keeps e-mail and phone behind Contact details, as links only once opened", async () => {
  const user = userEvent.setup();
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: { ...anna, aliases: [alias] },
      projects: { items: [], next_cursor: null },
      tasks: { items: [], next_cursor: null },
    }),
  });
  const { container } = render(contactRoot(work));
  expect(
    await screen.findByRole("heading", {
      level: 3,
      name: dl.aboutContact("Anna"),
    }),
  ).toBeInTheDocument();
  expect(screen.getByText(anna.context_note as string)).toHaveClass(
    "work-contact-about",
  );
  // Email and phone are hidden until the collapsible "Contact details" opens: no labels, no links.
  // The button names the section and what is there ("Contact details Email and phone"), so the name is a prefix.
  const ways = screen.getByRole("button", {
    name: new RegExp(`^${dl.waysToReach}`),
  });
  expect(ways).toHaveTextContent("Email and phone");
  // The shared fold row: the meta line is its own element, ⌄ comes last.
  expect(ways).toHaveClass("sk-fold");
  expect(ways.closest("section")).toHaveClass("work-contact-ways");
  expect(ways.querySelector(".sk-fold-meta")).toHaveTextContent(
    "Email and phone",
  );
  expect(ways.lastElementChild?.tagName.toLowerCase()).toBe("svg");
  expect(ways).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText(anna.email as string)).toBeNull();
  expect(screen.queryByText(anna.phone as string)).toBeNull();
  expect(container.querySelector("a")).toBeNull();
  await user.click(ways);
  expect(ways).toHaveAttribute("aria-expanded", "true");
  expect(
    screen.getByRole("link", { name: anna.email as string }),
  ).toHaveAttribute("href", `mailto:${anna.email}`);
  expect(
    screen.getByRole("link", { name: anna.phone as string }),
  ).toHaveAttribute("href", "tel:+46700000001");
  expect(screen.queryByText(`${workEn.email}: ${anna.email}`)).toBeNull();
  expect(screen.queryByText(`${workEn.phone}: ${anna.phone}`)).toBeNull();
  // The aliases are one meta line, "Also known as Annan A", with no button under the name.
  expect(document.querySelector(".work-alias-line")).toHaveTextContent(
    `${workEn.aliasLabel()} ${alias.value}`,
  );
  expect(screen.getByText(alias.value)).toBeInTheDocument();
  // Nicknames are edited in the editor: the ⋯ menu has no separate nickname entry.
  await openMoreMenu(user);
  expect(screen.getByRole("button", { name: workEn.edit })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.addAlias })).toBeNull();
  // Only the e-mail and the phone are links; the note and the aliases are not.
  expect(container.querySelectorAll("a")).toHaveLength(2);
});

it("shows no alias line when there are none, and the nickname list only inside the editor", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(contactRoot(work));
  const name = await screen.findByRole("heading", { name: anna.display_name });
  expect(document.querySelector(".work-alias-line")).toBeNull();
  expect(screen.queryByRole("button", { name: workEn.addAlias })).toBeNull();
  expect(screen.queryByLabelText(workEn.aliasValue)).toBeNull();
  await openMoreMenu(user);
  expect(screen.queryByRole("button", { name: workEn.addAlias })).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.edit }));
  const group = await screen.findByRole("group", {
    name: workEn.aliasesHeading,
  });
  expect(within(group).getByText(workEn.noAliases)).toBeInTheDocument();
  const add = within(group).getByRole("button", { name: workEn.addAlias });
  expect(
    name.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(document.querySelector(".work-alias-line")).toBeNull();
});

it("shows the aliases as one line, 'Also known as X, Y', under the name", async () => {
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: {
        ...anna,
        aliases: [alias, { ...alias, id: `${aliasId}-2`, value: "Annie" }],
      },
      projects: { items: [], next_cursor: null },
      tasks: { items: [], next_cursor: null },
    }),
  });
  render(contactRoot(work));
  const name = await screen.findByRole("heading", { name: anna.display_name });
  const row = await waitFor(() => {
    const line = document.querySelector<HTMLElement>(".work-alias-line");
    if (!line) throw new Error("no alias line yet");
    return line;
  });
  expect(row).toHaveTextContent(`${workEn.aliasLabel()} ${alias.value}, Annie`);
  expect(row.querySelector("button")).toBeNull();
  expect(
    name.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: workEn.addAlias }),
  ).not.toBeInTheDocument();
});

it("shows the Contact's projects and opens a Project from them", async () => {
  const user = userEvent.setup();
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: anna,
      projects: {
        items: [
          { id: projectA.id, title: projectA.title, status: projectA.status },
        ],
        next_cursor: null,
      },
      tasks: { items: [], next_cursor: null },
    }),
  });
  render(contactRoot(work));
  await user.click(await screen.findByRole("button", { name: projectA.title }));
  expect(
    await screen.findByRole("heading", { level: 2, name: projectA.title }),
  ).toBeInTheDocument();
  expect(work.getProject).toHaveBeenCalledWith(projectA.id);
});

it("saves only the changed Contact fields with the expected version and a key", async () => {
  const user = userEvent.setup();
  const updateContact = vi.fn().mockResolvedValue({
    contact: {
      ...anna,
      phone: null,
      context_note: "Ny anteckning",
      version: 2,
    },
  });
  const work = transport({ updateContact });
  render(contactRoot(work));
  await openEdit(user);
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(updateContact).not.toHaveBeenCalled();
  await openEdit(user);
  await user.clear(screen.getByLabelText(workEn.phone));
  const note = screen.getByLabelText(workEn.contextNote);
  await user.clear(note);
  await user.type(note, "Ny anteckning");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateContact).toHaveBeenCalledTimes(1);
  expect(updateContact).toHaveBeenCalledWith(
    anna.id,
    1,
    { phone: null, context_note: "Ny anteckning" },
    expect.stringMatching(KEY),
  );
  expect(screen.queryByRole("form", { name: workEn.edit })).toBeNull();
});

it("shows relationship, role and organization as one muted profile line under the name, without labels, and the address behind Contact details", async () => {
  const user = userEvent.setup();
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const profiled = {
    ...anna,
    relationship: "Kund",
    organization: "Acme AB",
    role: "Inköpschef",
    address: "Storgatan 1, Stockholm",
  };
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: profiled,
      projects: { items: [], next_cursor: null },
      tasks: { items: [], next_cursor: null },
    }),
  });
  render(contactRoot(work));

  // The order of the list row: relationship, role, organization (not the old relation, organization, role).
  const profile = await screen.findByText("Kund · Inköpschef · Acme AB");
  expect(profile).toHaveClass("work-contact-profile");
  expect(profile).not.toHaveClass("work-alias-line");
  // Right under the name.
  expect(profile.previousElementSibling).toBe(
    screen.getByRole("heading", { level: 2, name: "Anna Andersson" }),
  );
  expect(screen.queryByText("Kund · Acme AB · Inköpschef")).toBeNull();
  expect(screen.queryByText(`${workEn.relationship}: Kund`)).toBeNull();
  expect(screen.queryByText(`${workEn.organization}: Acme AB`)).toBeNull();
  expect(screen.queryByText(`${workEn.role}: Inköpschef`)).toBeNull();
  // The address waits in the collapsed "Contact details" section, as plain text.
  expect(screen.queryByText("Storgatan 1, Stockholm")).toBeNull();
  await user.click(
    screen.getByRole("button", { name: new RegExp(`^${dl.waysToReach}`) }),
  );
  expect(screen.getByText("Storgatan 1, Stockholm")).toBeInTheDocument();
  expect(
    screen.queryByText(`${workEn.address}: Storgatan 1, Stockholm`),
  ).toBeNull();
});

it("the Contact's profile line is character for character the list row's meta line of the same Contact, and empty parts are left out", async () => {
  const cases = [
    { relationship: "Kund", role: "Inköpschef", organization: "Acme AB" },
    { relationship: "Granne", role: null, organization: null },
    { relationship: null, role: "CFO", organization: "Beta" },
    { relationship: " ", role: "", organization: "Gamma" },
  ];
  for (const fields of cases) {
    const profiled = { ...anna, ...fields };
    const { unmount } = render(
      contactRoot(
        transport({
          getContactContext: vi.fn().mockResolvedValue({
            contact: profiled,
            projects: { items: [], next_cursor: null },
            tasks: { items: [], next_cursor: null },
          }),
        }),
      ),
    );
    await screen.findByRole("heading", { level: 2, name: "Anna Andersson" });
    const detail = document.querySelector(".work-contact-profile")?.textContent;
    unmount();

    const list = render(
      <ContactsView
        frame={{
          kind: "contacts",
          q: "",
          includeArchived: false,
          page: {
            items: [
              {
                id: profiled.id,
                display_name: profiled.display_name,
                archived: false,
                relationship: profiled.relationship,
                role: profiled.role,
                organization: profiled.organization,
              },
            ],
            next_cursor: null,
            q: "",
            includeArchived: false,
          },
        }}
        onChange={vi.fn()}
        transport={transport({})}
        labels={workEn}
        moves={0}
        onOpen={vi.fn()}
        shortcuts={false}
      />,
    );
    const row = document.querySelector(".sk-row-secondary")?.textContent;
    list.unmount();
    expect(detail).toBeTruthy();
    expect(detail).toBe(row);
  }
});

it("draws no profile line for a Contact with no relationship, role or organization", async () => {
  render(
    contactRoot(
      transport({
        getContactContext: vi.fn().mockResolvedValue({
          contact: { ...anna, relationship: " ", role: "", organization: null },
          projects: { items: [], next_cursor: null },
          tasks: { items: [], next_cursor: null },
        }),
      }),
    ),
  );
  await screen.findByRole("heading", { level: 2, name: "Anna Andersson" });
  expect(document.querySelector(".work-contact-profile")).toBeNull();
  expect(document.querySelector(".work-alias-line")).toBeNull();
});

it("sends only the changed organization to update_contact", async () => {
  const user = userEvent.setup();
  const profiled = { ...anna, organization: "Acme AB" };
  const updateContact = vi
    .fn()
    .mockResolvedValue({ contact: { ...profiled, version: 2 } });
  const work = transport({
    getContactContext: vi.fn().mockResolvedValue({
      contact: profiled,
      projects: { items: [], next_cursor: null },
      tasks: { items: [], next_cursor: null },
    }),
    updateContact,
  });
  render(contactRoot(work));
  await openEdit(user);
  const organization = screen.getByLabelText(workEn.organization);
  await user.clear(organization);
  await user.type(organization, "Nordic AB");
  await user.click(screen.getByRole("button", { name: workEn.save }));

  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateContact).toHaveBeenCalledTimes(1);
  expect(updateContact).toHaveBeenCalledWith(
    anna.id,
    1,
    { organization: "Nordic AB" },
    expect.stringMatching(KEY),
  );
});

it("shows a conflict on save, reloads the latest Contact and keeps the typed note", async () => {
  const user = userEvent.setup();
  const latest = { ...anna, context_note: "Annan anteckning", version: 2 };
  const getContactContext = vi
    .fn()
    .mockResolvedValueOnce({
      contact: anna,
      projects: { items: [], next_cursor: null },
      tasks: { items: annaTasks, next_cursor: null },
    })
    .mockResolvedValue({
      contact: latest,
      projects: { items: [], next_cursor: null },
      tasks: { items: annaTasks, next_cursor: null },
    });
  const updateContact = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("conflict"))
    .mockResolvedValue({
      contact: { ...latest, context_note: "Min anteckning", version: 3 },
    });
  const work = transport({ getContactContext, updateContact });
  render(contactRoot(work));
  await openEdit(user);
  const note = screen.getByLabelText(workEn.contextNote);
  await user.clear(note);
  await user.type(note, "Min anteckning");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent(workEn.contactEditConflict);
  await waitFor(() => expect(banner).toHaveFocus());
  await user.click(within(banner).getByRole("button", { name: workEn.reload }));
  await waitFor(() => expect(getContactContext).toHaveBeenCalledTimes(2));
  expect(screen.getByLabelText(workEn.contextNote)).toHaveValue(
    "Min anteckning",
  );
  expect(screen.queryByRole("alert")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(await screen.findByText(workEn.saved)).toBeInTheDocument();
  expect(updateContact).toHaveBeenCalledTimes(2);
  expect(updateContact.mock.calls[0]).toEqual([
    anna.id,
    1,
    { context_note: "Min anteckning" },
    expect.stringMatching(KEY),
  ]);
  expect(updateContact.mock.calls[1]).toEqual([
    anna.id,
    2,
    { context_note: "Min anteckning" },
    expect.stringMatching(KEY),
  ]);
  expect(keyOf(updateContact, 1)).not.toBe(keyOf(updateContact, 0));
});

it("blocks an invalid email with the invalid text and sends nothing", async () => {
  const user = userEvent.setup();
  const updateContact = vi.fn();
  const work = transport({ updateContact });
  render(contactRoot(work));
  await openEdit(user);
  const email = screen.getByLabelText(workEn.email);
  await user.clear(email);
  await user.type(email, "anna.example.test");
  await user.click(screen.getByRole("button", { name: workEn.save }));
  expect(screen.getByText(workEn.invalidChange)).toBeInTheDocument();
  expect(email).toHaveAttribute("aria-invalid", "true");
  expect(email).toHaveFocus();
  expect(updateContact).not.toHaveBeenCalled();
});

it("adds an alias with the expected version, clears the field and lists the alias", async () => {
  const user = userEvent.setup();
  const addContactAlias = vi.fn().mockResolvedValue({
    contact: { ...anna, aliases: [alias], version: 2 },
  });
  const work = transport({ addContactAlias });
  render(contactRoot(work));
  await openEdit(user);
  // A field typed before the nickname stays in the editor after the nickname is written.
  await user.type(screen.getByLabelText(workEn.nameLabel), " Svensson");
  await user.type(await screen.findByLabelText(workEn.aliasValue), "Annan A");
  await user.click(screen.getByRole("button", { name: workEn.addAlias }));
  expect(
    await screen.findByRole("button", {
      name: workEn.removeAliasFor(alias.value),
    }),
  ).toBeInTheDocument();
  expect(addContactAlias).toHaveBeenCalledWith(
    anna.id,
    1,
    "Annan A",
    expect.stringMatching(KEY),
  );
  expect(screen.getByLabelText(workEn.aliasValue)).toHaveValue("");
  expect(screen.getByLabelText(workEn.nameLabel)).toHaveValue(
    `${anna.display_name} Svensson`,
  );
});

it("adds the alias on Enter in the nickname field without saving the Contact", async () => {
  const user = userEvent.setup();
  const addContactAlias = vi.fn().mockResolvedValue({
    contact: { ...anna, aliases: [alias], version: 2 },
  });
  const updateContact = vi.fn();
  render(contactRoot(transport({ addContactAlias, updateContact })));
  await openEdit(user);
  await user.type(
    await screen.findByLabelText(workEn.aliasValue),
    "Annan A{Enter}",
  );
  await waitFor(() => expect(addContactAlias).toHaveBeenCalledTimes(1));
  expect(updateContact).not.toHaveBeenCalled();
});

it("retries a failed alias add with the same value and the same key", async () => {
  const user = userEvent.setup();
  const addContactAlias = vi
    .fn()
    .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
    .mockResolvedValue({ contact: { ...anna, aliases: [alias], version: 2 } });
  const work = transport({ addContactAlias });
  render(contactRoot(work));
  await openEdit(user);
  await user.type(await screen.findByLabelText(workEn.aliasValue), "Annan A");
  await user.click(screen.getByRole("button", { name: workEn.addAlias }));
  expect(await screen.findByText(workEn.contactSaveFailed)).toBeInTheDocument();
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("button", {
      name: workEn.removeAliasFor(alias.value),
    }),
  ).toBeInTheDocument();
  expect(addContactAlias).toHaveBeenCalledTimes(2);
  expect(addContactAlias.mock.calls[1]).toEqual(addContactAlias.mock.calls[0]);
});

it("removes an alias only after a confirmation and names the button after the alias", async () => {
  const user = userEvent.setup();
  const removeContactAlias = vi.fn().mockResolvedValue({
    contact: { ...anna, aliases: [], version: 2 },
  });
  const work = transport({
    getContactContext: vi
      .fn()
      .mockImplementation(() => contextOf({ ...anna, aliases: [alias] })),
    removeContactAlias,
  });
  render(contactRoot(work));
  await openEdit(user);
  await user.click(
    await screen.findByRole("button", {
      name: workEn.removeAliasFor(alias.value),
    }),
  );
  expect(removeContactAlias).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: workEn.confirmChange }),
  ).toHaveFocus();
  await user.click(screen.getByRole("button", { name: workEn.confirmChange }));
  // With no aliases left the line goes; the editor stays open with the empty list and the add field.
  await waitFor(() =>
    expect(
      screen.queryByRole("button", {
        name: workEn.removeAliasFor(alias.value),
      }),
    ).toBeNull(),
  );
  expect(document.querySelector(".work-alias-line")).toBeNull();
  expect(screen.getByLabelText(workEn.aliasValue)).toBeInTheDocument();
  expect(screen.getByText(workEn.noAliases)).toBeInTheDocument();
  expect(removeContactAlias).toHaveBeenCalledTimes(1);
  expect(removeContactAlias).toHaveBeenCalledWith(
    anna.id,
    aliasId,
    1,
    expect.stringMatching(KEY),
  );
});

it("archives at once, shows the receipt with Undo, and restores the Contact from the menu", async () => {
  const user = userEvent.setup();
  const archiveContact = vi.fn().mockResolvedValue({
    contact: {
      ...anna,
      archived: true,
      archived_at: "2026-10-25T10:00:00Z",
      version: 2,
    },
  });
  const restoreContact = vi
    .fn()
    .mockResolvedValue({ contact: { ...anna, version: 3 } });
  const work = transport({ archiveContact, restoreContact });
  render(contactRoot(work));
  await openMoreMenu(user);
  await user.click(
    await screen.findByRole("button", { name: workEn.archiveContact }),
  );
  // No question first: the write goes out and the menu closes.
  expect(
    await screen.findByText(workEn.contactArchived, {
      selector: "[role=status]",
    }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: workEn.confirmChange }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: workEn.archiveContact }),
  ).toBeNull();
  expect(screen.getByText(workEn.archivedReadOnly)).toBeInTheDocument();
  // The receipt already says it was saved: no plain "Saved" line beside it.
  expect(screen.queryByText(workEn.saved)).toBeNull();
  expect(screen.queryByLabelText(workEn.aliasValue)).toBeNull();
  expect(archiveContact).toHaveBeenCalledWith(
    anna.id,
    1,
    expect.stringMatching(KEY),
  );
  // The keyboard stays on the page, on the receipt's Undo.
  await waitFor(() =>
    expect(screen.getByRole("button", { name: workEn.undo })).toHaveFocus(),
  );
  await openMoreMenu(user);
  expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.restoreContact }));
  await waitFor(() =>
    expect(screen.queryByText(workEn.contactArchived)).toBeNull(),
  );
  expect(screen.queryByText(workEn.archivedReadOnly)).toBeNull();
  expect(restoreContact).toHaveBeenCalledWith(
    anna.id,
    2,
    expect.stringMatching(KEY),
  );
  await openMoreMenu(user);
  expect(screen.getByRole("button", { name: workEn.edit })).toBeInTheDocument();
});

it("Undo on the archive receipt restores the Contact at the version the archive left, and a failed Undo says so and can be retried", async () => {
  const user = userEvent.setup();
  const archiveContact = vi.fn().mockResolvedValue({
    contact: { ...anna, archived: true, version: 2 },
  });
  const restoreContact = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ contact: { ...anna, version: 3 } });
  const work = transport({ archiveContact, restoreContact });
  render(contactRoot(work));
  await openMoreMenu(user);
  await user.click(
    await screen.findByRole("button", { name: workEn.archiveContact }),
  );
  await user.click(await screen.findByRole("button", { name: workEn.undo }));
  const failed = await screen.findByText(workEn.contactSaveFailed, {
    exact: false,
  });
  expect(failed).toBeInTheDocument();
  // The receipt stays while the Contact is still archived.
  expect(screen.getByText(workEn.contactArchived)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  await waitFor(() =>
    expect(screen.queryByText(workEn.contactArchived)).toBeNull(),
  );
  expect(restoreContact).toHaveBeenCalledTimes(2);
  expect(restoreContact).toHaveBeenNthCalledWith(
    1,
    anna.id,
    2,
    expect.stringMatching(KEY),
  );
  // The retry replays the same action, so it carries the same key.
  expect(restoreContact.mock.calls[1]?.[2]).toBe(
    restoreContact.mock.calls[0]?.[2],
  );
});

it("shows the archive receipt in Swedish", async () => {
  const user = userEvent.setup();
  render(contactRoot(transport(), workSv));
  await user.click(
    await screen.findByRole("button", { name: workSv.moreActions }),
  );
  await user.click(screen.getByRole("button", { name: workSv.archiveContact }));
  expect(
    await screen.findByText("Kontakten är arkiverad."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Ångra" })).toBeInTheDocument();
});

it("puts Edit and the archive action behind the ⋯ menu on the heading row, with no pen", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(contactRoot(work));
  const heading = await screen.findByRole("heading", {
    name: anna.display_name,
  });
  const more = screen.getByRole("button", { name: workEn.moreActions });
  expect(heading.parentElement).toContainElement(more);
  // Closed, the menu holds nothing: neither Edit nor Archive is on the page, and there is no pen.
  expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
  expect(
    screen.queryByRole("button", { name: workEn.archiveContact }),
  ).toBeNull();
  await user.click(more);
  // Edit is the first entry, Archive follows it.
  const edit = screen.getByRole("button", { name: workEn.edit });
  const archive = screen.getByRole("button", { name: workEn.archiveContact });
  expect(
    edit.compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("shows a refused archive as calm text without retry", async () => {
  const user = userEvent.setup();
  const archiveContact = vi
    .fn()
    .mockRejectedValue(new HostToolError("forbidden"));
  const work = transport({ archiveContact });
  render(contactRoot(work));
  await openMoreMenu(user);
  await user.click(
    await screen.findByRole("button", { name: workEn.archiveContact }),
  );
  expect(await screen.findByText(workEn.forbiddenWrite)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
  expect(archiveContact).toHaveBeenCalledTimes(1);
});

it("sends one update for two save clicks dispatched before React re-renders", async () => {
  const user = userEvent.setup();
  const updateContact = vi.fn(() => new Promise<never>(() => {}));
  const work = transport({ updateContact });
  render(contactRoot(work));
  await openEdit(user);
  await user.type(screen.getByLabelText(workEn.nameLabel), " Svensson");
  const save = screen.getByRole("button", { name: workEn.save });
  fireEvent.click(save);
  fireEvent.click(save);
  expect(updateContact).toHaveBeenCalledTimes(1);
});

it("names the alias and archive controls in Swedish", async () => {
  const user = userEvent.setup();
  const work = transport({
    getContactContext: vi
      .fn()
      .mockImplementation(() => contextOf({ ...anna, aliases: [alias] })),
  });
  render(contactRoot(work, workSv));
  await user.click(
    await screen.findByRole("button", { name: workSv.moreActions }),
  );
  // No separate nickname entry in the menu; Arkivera sits there under Redigera.
  expect(screen.queryByRole("button", { name: "Ändra namn" })).toBeNull();
  expect(screen.getByRole("button", { name: "Arkivera" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workSv.edit }));
  expect(
    await screen.findByRole("group", { name: "Även kallad" }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("button", {
      name: "Ta bort namnet Annan A",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Lägg till alternativt namn" }),
  ).toBeInTheDocument();
});
