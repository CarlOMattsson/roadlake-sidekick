import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { WorkView } from "@/features/work-app/view/work-view";
import { hierarchyDetailLabelsFor } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  rootFromToolResult,
  type WorkContactSummary,
  type WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  KEY,
  anna,
  bo,
  contactRoot,
  keyOf,
  rootTask,
  taskA,
  transport,
} from "./helpers/work-app-fixtures";

/** Rows of list_contacts (ContactSummaryRecord), as the Contact list shows them. */
const listAnna: WorkContactSummary = {
  id: anna.id,
  display_name: anna.display_name,
  archived: false,
};

const listBo: WorkContactSummary = {
  id: bo.id,
  display_name: bo.display_name,
  archived: false,
};

const listCecilia: WorkContactSummary = {
  id: "019f0000-0000-7000-8000-0000000000c5",
  display_name: "Cecilia Arkivsson",
  archived: true,
};

const noFilters = { q: "", includeArchived: false };

/** An archived Contact's row also holds its "Archived" chip, so its name is matched by its start. */
const archivedRowName = new RegExp(
  `^${listCecilia.display_name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
);

function contactsRoot(
  work: WorkTransport,
  result: unknown = { contacts: [listAnna, listBo], next_cursor: null },
  labels = workEn,
) {
  return (
    <WorkView
      transport={work}
      initial={rootFromToolResult(result)}
      labels={labels}
    />
  );
}

it("opens the Contact list as the root of a list_contacts result and leaves other results alone", () => {
  const root = rootFromToolResult({
    contacts: [listAnna],
    next_cursor: "page-2",
  });
  expect(root).toEqual({
    kind: "contacts",
    q: "",
    includeArchived: false,
    page: {
      items: [listAnna],
      next_cursor: "page-2",
      q: "",
      includeArchived: false,
    },
  });
  expect(rootFromToolResult({ contacts: [] })).toMatchObject({
    kind: "contacts",
  });
  expect(rootFromToolResult({ contacts: [{ name: "x" }] })).toBeUndefined();
  expect(
    rootFromToolResult({
      contact: anna,
      projects: { items: [] },
      tasks: { items: [] },
    }),
  ).toMatchObject({ kind: "contact", id: anna.id, context: { contact: anna } });
  expect(rootFromToolResult({ task: taskA })).toEqual({
    kind: "task",
    id: taskA.id,
    task: taskA,
  });
});

it("shows the list from the tool result without reading, as a labelled list of rows that open a Contact", async () => {
  const user = userEvent.setup();
  const work = transport();
  render(contactsRoot(work));
  expect(
    screen.getByRole("heading", { level: 2, name: workEn.contacts }),
  ).toBeInTheDocument();
  const list = screen.getByRole("list", { name: workEn.contacts });
  expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByLabelText(workEn.searchContacts)).toHaveAttribute(
    "type",
    "search",
  );
  expect(work.listContacts).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: /^Tillbaka till / })).toBeNull();
  await user.click(
    within(list).getByRole("button", { name: listAnna.display_name }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toBeInTheDocument();
  expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
});

it("shows the search and archive switch a list_contacts result answered, and Show more repeats them", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockResolvedValue({ items: [listCecilia], next_cursor: null });
  const work = transport({ listContacts: list });
  render(
    contactsRoot(work, {
      contacts: [listAnna],
      next_cursor: "p2",
      q: "anna",
      include_archived: true,
    }),
  );
  expect(screen.getByLabelText(workEn.searchContacts)).toHaveValue("anna");
  await user.click(screen.getByRole("button", { name: workEn.moreActions }));
  expect(
    screen.getByRole("checkbox", { name: workEn.showArchived }),
  ).toBeChecked();
  expect(work.listContacts).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: workEn.more }));
  expect(list).toHaveBeenCalledWith({ q: "anna", includeArchived: true }, "p2");
});

it("opens a Contact from the list and goes back to the same search and list without reading again", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockResolvedValue({ items: [listBo], next_cursor: null });
  const work = transport({ listContacts: list });
  render(contactsRoot(work));
  await user.type(screen.getByLabelText(workEn.searchContacts), "Bo");
  await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
  await user.click(
    await screen.findByRole("button", { name: listBo.display_name }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toBeInTheDocument();
  expect(work.getContactContext).toHaveBeenCalledWith(bo.id);
  // The list is already in the stack, so the Contact does not offer a second one.
  expect(screen.queryByRole("button", { name: workEn.allContacts })).toBeNull();
  await user.click(
    screen.getByRole("button", { name: `Tillbaka till ${workEn.contacts}` }),
  );
  expect(screen.getByLabelText(workEn.searchContacts)).toHaveValue("Bo");
  expect(
    screen.getByRole("button", { name: listBo.display_name }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: listAnna.display_name }),
  ).toBeNull();
  expect(list).toHaveBeenCalledTimes(1);
});

it("waits for a pause before searching and searches the trimmed text once", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockResolvedValue({ items: [listBo], next_cursor: null });
  const work = transport({ listContacts: list });
  render(contactsRoot(work));
  await user.type(screen.getByLabelText(workEn.searchContacts), " Bo ");
  expect(list).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(workEn.loading);
  await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
  expect(list).toHaveBeenCalledWith({ q: "Bo", includeArchived: false });
  expect(
    await screen.findByRole("button", { name: listBo.display_name }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: listAnna.display_name }),
  ).toBeNull();
});

it("ignores the answer to an older search", async () => {
  const user = userEvent.setup();
  let resolveOld!: (value: unknown) => void;
  const list = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue({ items: [listBo], next_cursor: null });
  const work = transport({ listContacts: list });
  render(contactsRoot(work));
  const input = screen.getByLabelText(workEn.searchContacts);
  await user.type(input, "An");
  await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
  await user.clear(input);
  await user.type(input, "Bo");
  expect(
    await screen.findByRole("button", { name: listBo.display_name }),
  ).toBeInTheDocument();
  act(() => {
    resolveOld({ items: [listAnna], next_cursor: null });
  });
  expect(
    screen.queryByRole("button", { name: listAnna.display_name }),
  ).toBeNull();
  expect(
    screen.getByRole("button", { name: listBo.display_name }),
  ).toBeInTheDocument();
  expect(list).toHaveBeenCalledTimes(2);
  expect(list).toHaveBeenLastCalledWith({ q: "Bo", includeArchived: false });
});

it("reads again with archived Contacts included and marks them", async () => {
  const user = userEvent.setup();
  const list = vi.fn((options: { q: string; includeArchived: boolean }) =>
    Promise.resolve({
      items: options.includeArchived
        ? [listAnna, listCecilia]
        : [listAnna, listBo],
      next_cursor: null,
    }),
  );
  const work = transport({ listContacts: list });
  render(contactsRoot(work));
  expect(screen.queryByText(workEn.archivedLabel)).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.moreActions }));
  await user.click(screen.getByRole("checkbox", { name: workEn.showArchived }));
  await waitFor(() =>
    expect(list).toHaveBeenCalledWith({ q: "", includeArchived: true }),
  );
  const row = (
    await screen.findByRole("button", { name: archivedRowName })
  ).closest("li")!;
  expect(within(row).getByText(workEn.archivedLabel)).toBeInTheDocument();
  // Switching back reads the list of active Contacts again.
  await user.click(screen.getByRole("checkbox", { name: workEn.showArchived }));
  await waitFor(() => expect(list).toHaveBeenCalledWith(noFilters));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: archivedRowName })).toBeNull(),
  );
});

it("shows more Contacts with the cursor of the shown search and removes the button on the last page", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockResolvedValue({ items: [listBo, listCecilia], next_cursor: null });
  const work = transport({ listContacts: list });
  render(
    contactsRoot(work, { contacts: [listAnna, listBo], next_cursor: "p2" }),
  );
  // Show more is the family's quiet text button.
  expect(screen.getByRole("button", { name: workEn.more })).toHaveClass(
    "sk-more",
  );
  await user.click(screen.getByRole("button", { name: workEn.more }));
  expect(
    await screen.findByRole("button", { name: archivedRowName }),
  ).toBeInTheDocument();
  expect(list).toHaveBeenCalledWith(noFilters, "p2");
  // The Contact that came on both pages is listed once.
  expect(
    screen.getAllByRole("button", { name: listBo.display_name }),
  ).toHaveLength(1);
  expect(screen.queryByRole("button", { name: workEn.more })).toBeNull();
});

it("keeps the shown Contacts and lets Show more be tried again when the next page fails", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ items: [listCecilia], next_cursor: null });
  render(
    contactsRoot(transport({ listContacts: list }), {
      contacts: [listAnna],
      next_cursor: "p2",
    }),
  );
  await user.click(screen.getByRole("button", { name: workEn.more }));
  expect(await screen.findByRole("alert")).toHaveTextContent(workEn.failed);
  expect(
    screen.getByRole("button", { name: listAnna.display_name }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: workEn.more }));
  expect(
    await screen.findByRole("button", { name: archivedRowName }),
  ).toBeInTheDocument();
});

it("shows empty, failed and forbidden lists calmly and retries a failed read", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ items: [], next_cursor: null });
  const work = transport({ listContacts: list });
  render(contactsRoot(work, { contacts: [listAnna] }));
  const input = screen.getByLabelText(workEn.searchContacts);
  await user.type(input, "Zz");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Couldn’t load your contacts",
  );
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByText(workEn.noContactMatches("Zz")),
  ).toBeInTheDocument();
  list.mockRejectedValueOnce(new HostToolError("forbidden"));
  await user.click(screen.getByRole("button", { name: workEn.moreActions }));
  await user.click(screen.getByRole("checkbox", { name: workEn.showArchived }));
  expect(await screen.findByText(workEn.contactsForbidden)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
});

it("shows a message when there are no Contacts at all", () => {
  render(contactsRoot(transport(), { contacts: [] }));
  expect(screen.getByText(workEn.noAnyContacts)).toBeInTheDocument();
});

it("opens the Contact list from the Contact and from the Task, and back again", async () => {
  const user = userEvent.setup();
  const list = vi
    .fn()
    .mockResolvedValue({ items: [listAnna, listBo], next_cursor: null });
  const work = transport({ listContacts: list });
  const { unmount } = render(contactRoot(work));
  await user.click(
    await screen.findByRole("button", { name: workEn.allContacts }),
  );
  expect(
    await screen.findByRole("list", { name: workEn.contacts }),
  ).toBeInTheDocument();
  expect(list).toHaveBeenCalledWith(noFilters);
  await user.click(
    screen.getByRole("button", { name: `Tillbaka till ${workEn.contact}` }),
  );
  expect(
    await screen.findByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toBeInTheDocument();
  unmount();
  render(rootTask(work));
  await user.click(
    await screen.findByRole("button", { name: workEn.allContacts }),
  );
  expect(
    await screen.findByRole("button", { name: listBo.display_name }),
  ).toBeInTheDocument();
});

it("creates a Contact from its name with one key per action, reuses it on retry and opens the new Contact", async () => {
  const user = userEvent.setup();
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const create = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ contact: bo });
  const list = vi
    .fn()
    .mockResolvedValue({ items: [listAnna, listBo], next_cursor: null });
  const work = transport({ createContact: create, listContacts: list });
  render(contactsRoot(work));
  await user.click(screen.getByRole("button", { name: workEn.newContact }));
  await user.type(
    screen.getByRole("textbox", { name: workEn.newContact }),
    "  Bo Berg ",
  );
  await user.click(screen.getByRole("button", { name: dl.add }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    workEn.contactCreateFailed,
  );
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("heading", { level: 2, name: "Anna Andersson" }),
  ).toBeInTheDocument();
  expect(create).toHaveBeenCalledTimes(2);
  // Only the name is sent: no e-mail any more.
  expect(create.mock.calls[0]?.[0]).toEqual({ display_name: "Bo Berg" });
  expect(create.mock.calls[1]).toEqual(create.mock.calls[0]);
  expect(keyOf(create, 0)).toMatch(KEY);
  expect(work.getContactContext).toHaveBeenCalledWith(bo.id);
  // The list read before lacks the new Contact, so going back reads it again.
  await user.click(
    screen.getByRole("button", { name: `Tillbaka till ${workEn.contacts}` }),
  );
  await waitFor(() => expect(list).toHaveBeenCalledWith(noFilters));
});

it("gives a changed name a new key after a refused create, which keeps the typed name", async () => {
  const user = userEvent.setup();
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const create = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ contact: bo });
  render(contactsRoot(transport({ createContact: create })));
  await user.click(screen.getByRole("button", { name: workEn.newContact }));
  const name = screen.getByRole("textbox", { name: workEn.newContact });
  await user.type(name, "Bo");
  await user.click(screen.getByRole("button", { name: dl.add }));
  await screen.findByRole("alert");
  // A refused create keeps the typed name, so the field is cleared before the changed name is typed.
  expect(name).toHaveValue("Bo");
  await user.clear(name);
  await user.type(name, "Bo Berg");
  await user.click(screen.getByRole("button", { name: dl.add }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
  expect(create.mock.calls[0]?.[0]).toEqual({ display_name: "Bo" });
  expect(create.mock.calls[1]?.[0]).toEqual({ display_name: "Bo Berg" });
  expect(keyOf(create, 1)).not.toBe(keyOf(create, 0));
});

it("does nothing on an empty Enter and refuses a name over the limit before any write", async () => {
  const user = userEvent.setup();
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const create = vi.fn();
  render(contactsRoot(transport({ createContact: create })));
  await user.click(screen.getByRole("button", { name: workEn.newContact }));
  const name = screen.getByRole("textbox", { name: workEn.newContact });
  expect(name).toHaveFocus();
  // Empty, the square is × (Close); Enter with nothing typed sends and says nothing.
  expect(screen.getByRole("button", { name: dl.close })).toBeInTheDocument();
  await user.keyboard("{Enter}");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(create).not.toHaveBeenCalled();
  fireEvent.input(name, { target: { value: "x".repeat(201) } });
  await user.click(screen.getByRole("button", { name: dl.add }));
  expect(screen.getByRole("alert")).toHaveTextContent(workEn.nameTooLong);
  expect(create).not.toHaveBeenCalled();
});

it("shows a refused new Contact calmly without retry and closes the field with Close, focus back on +", async () => {
  const user = userEvent.setup();
  const dl = hierarchyDetailLabelsFor(workEn.dateLocale);
  const create = vi
    .fn()
    .mockRejectedValue(new HostToolError("validation_error"));
  render(contactsRoot(transport({ createContact: create })));
  await user.click(screen.getByRole("button", { name: workEn.newContact }));
  await user.type(
    screen.getByRole("textbox", { name: workEn.newContact }),
    "Bo",
  );
  await user.click(screen.getByRole("button", { name: dl.add }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    workEn.invalidChange,
  );
  // A refused create keeps the typed name in the field.
  const name = screen.getByRole("textbox", { name: workEn.newContact });
  expect(name).toHaveValue("Bo");
  expect(screen.queryByRole("button", { name: workEn.retry })).toBeNull();
  // With text the square is +; clear the field first so that × (Close) is shown.
  await user.clear(name);
  await user.click(screen.getByRole("button", { name: dl.close }));
  expect(screen.queryByRole("textbox", { name: workEn.newContact })).toBeNull();
  expect(screen.getByRole("button", { name: workEn.newContact })).toHaveFocus();
});

it("shows the Contact list in Swedish", () => {
  render(contactsRoot(transport(), undefined, workSv));
  expect(screen.getByLabelText(workSv.searchContacts)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: workSv.moreActions }));
  expect(
    screen.getByRole("checkbox", { name: workSv.showArchived }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: workSv.newContact }),
  ).toBeInTheDocument();
  expect(workSv.allContacts).not.toBe(workEn.allContacts);
});
