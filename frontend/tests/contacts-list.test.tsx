import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import { contactsRoomLabelsEn } from "@/features/work-app/contacts/contacts-room-labels";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkContactsFrame,
  WorkContactSummary,
  WorkTransport,
} from "@/features/work-app/transport/transport";

function contact(name: string, archived = false): WorkContactSummary {
  return { id: `id-${name}`, display_name: name, archived };
}

function transport(listContacts = vi.fn()): WorkTransport {
  return { listContacts } as unknown as WorkTransport;
}

/** A frame whose page already shows `items` for the empty search, or no page when `items` is undefined. */
function frameOf(items?: WorkContactSummary[], q = ""): WorkContactsFrame {
  return {
    kind: "contacts",
    q,
    includeArchived: false,
    page: items && { items, next_cursor: null, q, includeArchived: false },
  };
}

function renderList(
  current: WorkContactsFrame,
  work = transport(),
  onOpen = vi.fn(),
  shortcuts = false,
) {
  const onChange =
    vi.fn<(before: WorkContactsFrame, next: WorkContactsFrame) => void>();
  render(
    <ContactsView
      frame={current}
      onChange={onChange}
      transport={work}
      labels={workEn}
      moves={0}
      onOpen={onOpen}
      shortcuts={shortcuts}
    />,
  );
  return { onChange, onOpen };
}

const SEVEN = [
  contact("Östen"),
  contact("Bo"),
  contact("Åsa"),
  contact("Anna Andersson"),
  contact("Ärla"),
  contact("Zeta"),
  contact("Cecilia"),
];

it("lists up to 15 Contacts as one flat list in Swedish order, with no letter headings", () => {
  renderList(frameOf(SEVEN));
  expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  // The name of each row, without its avatar of initials that leads the row.
  expect(
    screen
      .getAllByRole("listitem")
      .map((row) => row.querySelector(".sk-row-primary")?.textContent),
  ).toEqual([
    "Anna Andersson",
    "Bo",
    "Cecilia",
    "Zeta",
    "Åsa",
    "Ärla",
    "Östen",
  ]);
});

it("groups Contacts under A–Ö letters when the list holds more than 15, with Å, Ä and Ö last", () => {
  const nine = Array.from({ length: 9 }, (_, i) => contact(`Dag ${i + 1}`));
  renderList(frameOf([...SEVEN, ...nine]));
  expect(
    screen
      .getAllByRole("heading", { level: 3 })
      .map((letter) => letter.textContent),
  ).toEqual(["A", "B", "C", "D", "Z", "Å", "Ä", "Ö"]);
});

it("opens a Contact from its row", async () => {
  const user = userEvent.setup();
  const { onOpen } = renderList(frameOf([contact("Anna Andersson")]));
  await user.click(screen.getByRole("button", { name: "Anna Andersson" }));
  expect(onOpen).toHaveBeenCalledWith({
    kind: "contact",
    id: "id-Anna Andersson",
  });
});

it("moves focus to the search field with /", async () => {
  const user = userEvent.setup();
  renderList(frameOf([contact("Anna Andersson")]), transport(), vi.fn(), true);
  const search = screen.getByLabelText(workEn.searchContacts);
  expect(search).not.toHaveFocus();
  await user.keyboard("/");
  expect(search).toHaveFocus();
  expect(search).toHaveValue("");
});

it("/ does nothing when shortcuts are off, as in an inline card", async () => {
  const user = userEvent.setup();
  renderList(frameOf([contact("Anna Andersson")]));
  const search = screen.getByLabelText(workEn.searchContacts);
  await user.keyboard("/");
  expect(search).not.toHaveFocus();
  expect(search).toHaveValue("");
});

it("a Contact row's meta line is relationship · role · organization of the fields that are set, and the address is never there", () => {
  const full = (name: string, fields: Partial<WorkContactSummary>) => ({
    ...contact(name),
    ...fields,
  });
  renderList(
    frameOf([
      full("Anna Andersson", {
        relationship: "Kollega",
        role: "Inköpare",
        organization: "Acme AB",
      }),
      full("Bo Berg", { relationship: "Granne" }),
      full("Cecilia Cederberg", { role: "CFO", organization: "Beta" }),
      full("David Dahl", { relationship: " ", role: "", organization: null }),
    ]),
  );
  const meta = (name: string) =>
    screen
      .getByRole("button", { name: new RegExp(`^${name}`) })
      .closest("li")!
      .querySelector(".sk-row-secondary")?.textContent;
  expect(meta("Anna Andersson")).toBe("Kollega · Inköpare · Acme AB");
  expect(meta("Bo Berg")).toBe("Granne");
  expect(meta("Cecilia Cederberg")).toBe("CFO · Beta");
  // No field set: no meta line at all.
  expect(meta("David Dahl")).toBeUndefined();
});

it("marks an archived Contact in its own row", () => {
  renderList(
    frameOf([contact("Anna Andersson"), contact("Cecilia Arkivsson", true)]),
  );
  const row = screen
    .getByRole("button", { name: /^Cecilia Arkivsson/ })
    .closest("li")!;
  expect(within(row).getByText(workEn.archivedLabel)).toBeInTheDocument();
  expect(screen.getAllByText(workEn.archivedLabel)).toHaveLength(1);
});

it("leads each row with a round avatar of the initials, hidden from assistive tech", () => {
  renderList(frameOf([contact("Anna Andersson")]));
  const row = screen
    .getByRole("button", { name: /^Anna Andersson/ })
    .closest("li")!;
  const avatar = within(row).getByText("AA");
  expect(avatar).toHaveClass("work-contact-avatar");
  expect(avatar).toHaveAttribute("aria-hidden", "true");
});

it("shows the empty state for no Contacts and for a search without matches", () => {
  const { unmount } = render(
    <ContactsView
      frame={frameOf([])}
      onChange={vi.fn()}
      transport={transport()}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText(workEn.noAnyContacts)).toBeInTheDocument();
  unmount();
  renderList(frameOf([], "zz"));
  expect(screen.getByText(workEn.noContactMatches("zz"))).toBeInTheDocument();
});

it("offers the hand-made way next to Tell Claude in the empty list: Add a contact opens the create field", async () => {
  const user = userEvent.setup();
  renderList(frameOf([]));
  await user.click(
    screen.getByRole("button", { name: contactsRoomLabelsEn.addContact }),
  );
  const field = await screen.findByRole("textbox", { name: workEn.newContact });
  expect(field).toHaveValue("");
  expect(field).toHaveFocus();
});

it("leaves out the Add a contact row where the host cannot create a Contact", () => {
  const work = {
    listContacts: vi.fn(),
    supportsTool: (name: string) => name !== "create_contact",
  } as unknown as WorkTransport;
  renderList(frameOf([]), work);
  expect(screen.getByText(workEn.noAnyContacts)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: contactsRoomLabelsEn.addContact }),
  ).toBeNull();
});

it("shows a failed first read and retries it", async () => {
  const user = userEvent.setup();
  const listContacts = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({
      items: [contact("Anna Andersson")],
      next_cursor: null,
    });
  const current = frameOf();
  const { onChange } = renderList(current, transport(listContacts));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn’t load your contacts",
  );
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
  const next = onChange.mock.calls[0]?.[1];
  expect(next?.page?.items).toEqual([contact("Anna Andersson")]);
  expect(listContacts).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("sticks letter headings below the host's overlay, and the search field asks for a search key", () => {
  const filler = Array.from({ length: 14 }, (_, i) => contact(`Anna ${i + 1}`));
  renderList(frameOf([contact("Anna Andersson"), contact("Bo"), ...filler]));
  const letter = screen.getByRole("heading", { level: 3, name: "A" });
  expect(letter).toHaveStyle({ position: "sticky" });
  expect(letter.style.top).toBe("var(--sk-sticky-top, 0px)");
  expect(screen.getByLabelText(workEn.searchContacts)).toHaveAttribute(
    "enterkeyhint",
    "search",
  );
});
