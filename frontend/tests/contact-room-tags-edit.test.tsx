import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { tagEn, tagSv } from "@/features/mcp-apps/ui/tag-labels";
import type { TagRecord } from "@/features/mcp-apps/ui/tag-vocabulary";
import { contactsRoomLabelsEn } from "@/features/work-app/contacts/contacts-room-labels";
import { ContactSummary } from "@/features/work-app/inline/inline-contact-summary";
import { inlineSummaryLabelsEn } from "@/features/work-app/inline/inline-summary-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  rootFromToolResult,
  type WorkContactSummary,
} from "@/features/work-app/transport/transport";
import {
  anna,
  contactRoot,
  openEdit,
  transport,
} from "./helpers/work-app-fixtures";

function tag(slug: string, contact: number): TagRecord {
  return {
    id: `019f0000-0000-7000-8000-${String(contact).padStart(12, "0")}`,
    slug,
    archived_at: null,
    label: slug,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    version: 1,
    usage: {
      contact,
      domain: null,
      journal_entry: null,
      process: null,
      project: null,
      task: null,
    },
  };
}

const vocabulary = [tag("viktig", 5), tag("styrelse", 2)];

function contextOf(contact: typeof anna) {
  return vi.fn().mockResolvedValue({
    contact,
    projects: { items: [], next_cursor: null },
    tasks: { items: [], next_cursor: null },
  });
}

const tagged: WorkContactSummary = {
  id: anna.id,
  display_name: anna.display_name,
  archived: false,
  tags: ["viktig"],
};

it("says no Contact has the chosen tag, with a way to clear the filter, instead of calling the list empty", async () => {
  const user = userEvent.setup();
  const listContacts = vi
    .fn()
    .mockResolvedValueOnce({ items: [], next_cursor: null })
    .mockResolvedValue({ items: [tagged], next_cursor: null });
  const work = transport({
    listContacts,
    listTags: vi.fn().mockResolvedValue(vocabulary),
  });
  render(
    <WorkView
      transport={work}
      initial={rootFromToolResult({ contacts: [tagged], next_cursor: null })}
      labels={workEn}
    />,
  );
  const group = await screen.findByRole("group", { name: tagEn.filter });
  await user.click(within(group).getByRole("button", { name: "styrelse" }));
  expect(
    await screen.findByText(
      contactsRoomLabelsEn.noContactsWithTags(["styrelse"], ""),
    ),
  ).toBeInTheDocument();
  // Not the empty room's text, its introduction or its example for Claude.
  expect(screen.queryByText(workEn.noAnyContacts)).not.toBeInTheDocument();
  expect(screen.queryByText(contactsRoomLabelsEn.emptyHint)).toBeNull();
  expect(
    screen.queryByText(new RegExp(contactsRoomLabelsEn.emptyAsk)),
  ).toBeNull();
  // The empty-state button is the way out; it clears the filter and the list is read again.
  const clear = screen
    .getAllByRole("button", { name: tagEn.clearLabel })
    .find((button) => button.classList.contains("work-add-row"));
  expect(clear).toBeDefined();
  // It has an icon like the other rows of its kind, so it reads as a button.
  expect(clear?.querySelector("svg")).not.toBeNull();
  await user.click(clear as HTMLElement);
  expect(listContacts).toHaveBeenLastCalledWith({
    q: "",
    includeArchived: false,
  });
  expect(
    await screen.findByRole("button", {
      name: new RegExp(`^${anna.display_name}`),
    }),
  ).toBeInTheDocument();
});

it("puts the Contact's tags before the ways to reach them, with 'All contacts' last", async () => {
  const work = transport({
    getContactContext: contextOf({ ...anna, tags: ["viktig"] }),
    listTags: vi.fn().mockResolvedValue(vocabulary),
  });
  render(contactRoot(work));
  const pills = await screen.findByText(`${tagEn.tags}: viktig`);
  const ways = screen.getByRole("button", { name: /Contact details/i });
  const all = screen.getByRole("button", { name: workEn.allContacts });
  const follows = (a: Node, b: Node) =>
    Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  expect(follows(pills, ways)).toBe(true);
  expect(follows(ways, all)).toBe(true);
  // The tags are not inside the folded ways.
  expect(ways.closest("section, div")?.contains(pills)).toBe(false);
});

it("replaces the read view with the form while editing, so nothing is shown twice", async () => {
  const user = userEvent.setup();
  const withAll = {
    ...anna,
    relationship: "Kund",
    tags: ["viktig"],
    aliases: [
      { id: "a1", value: "Annan A", created_at: "2026-10-25T10:00:00Z" },
    ],
  };
  const work = transport({
    getContactContext: contextOf(withAll),
    listTags: vi.fn().mockResolvedValue(vocabulary),
  });
  render(contactRoot(work));
  const note = await screen.findByText(anna.context_note as string);
  expect(screen.getByText(`${tagEn.tags}: viktig`)).toBeInTheDocument();
  expect(document.querySelector(".work-alias-line")).not.toBeNull();
  expect(document.querySelector(".work-contact-profile")).not.toBeNull();
  await openEdit(user);
  // The note stays only in the form's own field; the heading stays as the page title.
  expect(note).not.toBeInTheDocument();
  expect(screen.getByLabelText(workEn.contextNote)).toHaveValue(
    anna.context_note,
  );
  expect(screen.queryByText(`${tagEn.tags}: viktig`)).toBeNull();
  expect(document.querySelector(".work-alias-line")).toBeNull();
  expect(document.querySelector(".work-contact-profile")).toBeNull();
  expect(screen.queryByRole("button", { name: /Contact details/i })).toBeNull();
  expect(
    screen.getByRole("heading", { level: 2, name: anna.display_name }),
  ).toBeInTheDocument();
  // The nicknames stay editable in the form, each only once.
  expect(screen.getAllByText("Annan A")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: workEn.cancel }));
  expect(
    await screen.findByText(anna.context_note as string),
  ).toBeInTheDocument();
  expect(screen.getByText(`${tagEn.tags}: viktig`)).toBeInTheDocument();
});

it("names the new-nickname field so it is not read as a rename (Swedish and English)", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(contactRoot(work, workSv));
  await user.click(
    await screen.findByRole("button", { name: workSv.moreActions }),
  );
  await user.click(await screen.findByRole("button", { name: workSv.edit }));
  expect(
    await screen.findByLabelText("Nytt alternativt namn"),
  ).toBeInTheDocument();
  expect(workSv.aliasValue).not.toBe(workSv.nameLabel);
  expect(workSv.aliasValue).toMatch(/alternativt/);
  expect(workEn.aliasValue).toBe("New alternative name");
});

it("shows two tags and +N on the inline Contact card, and nothing for a Contact without tags", () => {
  const { container, rerender } = render(
    <ContactSummary
      kindLabel="Contact"
      name="Anna Andersson"
      email={null}
      tags={["viktig", "familj", "styrelse"]}
      labels={inlineSummaryLabelsEn}
      onOpen={vi.fn()}
    />,
  );
  const drawn = container.querySelectorAll('.sk-tag[aria-hidden="true"]');
  expect([...drawn].map((pill) => pill.textContent)).toEqual([
    "viktig",
    "familj",
    "+1",
  ]);
  expect(container.textContent).toContain(
    `${tagEn.tags}: viktig, familj and 1 more`,
  );
  rerender(
    <ContactSummary
      kindLabel="Contact"
      name="Anna Andersson"
      email={null}
      labels={inlineSummaryLabelsEn}
      onOpen={vi.fn()}
    />,
  );
  expect(container.querySelector(".sk-tags")).toBeNull();
  expect(tagSv.tags).toBe("Taggar");
});
