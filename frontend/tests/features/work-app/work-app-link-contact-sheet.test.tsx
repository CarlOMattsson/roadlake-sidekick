import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type { WorkContact } from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  KEY,
  anna,
  bo,
  rootTask,
  taskA,
  transport,
} from "@tests/helpers/work-app-fixtures";

/** Not linked to taskA, so a search can offer it. */
const erik: WorkContact = {
  id: "019f0000-0000-7000-8000-0000000000c3",
  display_name: "Erik Lindgren",
};

/** Opens the sheet from "+ Koppla kontakt" / "+ Link contact" once the Task's contacts are drawn. */
async function openSheet(
  user: ReturnType<typeof userEvent.setup>,
  t: WorkLabels = workEn,
) {
  await screen.findByRole("button", { name: anna.display_name });
  await user.click(screen.getByRole("button", { name: t.linkContact }));
  return screen.getByLabelText(t.linkContact);
}

it("filters the contacts as the name is typed and shows a linked hit without offering it", async () => {
  const user = userEvent.setup();
  const search = vi.fn((q: string) =>
    Promise.resolve({
      items: [anna, erik].filter((contact) =>
        contact.display_name.toLowerCase().includes(q.toLowerCase()),
      ),
      next_cursor: null,
    }),
  );
  render(rootTask(transport({ searchContacts: search })));
  const input = await openSheet(user);
  expect(input).toHaveFocus();
  expect(input).toHaveAttribute("placeholder", workEn.contactSearchPlaceholder);
  expect(screen.getByText(workEn.contactSearchHint)).toBeInTheDocument();

  await user.type(input, "Eri");
  expect(
    await screen.findByRole("button", { name: erik.display_name }),
  ).toBeInTheDocument();
  expect(screen.queryByText(workEn.contactAlreadyLinked)).toBeNull();

  await user.clear(input);
  await user.type(input, "An");
  expect(
    await screen.findByText(workEn.contactAlreadyLinked),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: erik.display_name })).toBeNull();
  // anna is linked: her only button is the contact row of the section, not a hit.
  expect(
    screen.getAllByRole("button", { name: anna.display_name }),
  ).toHaveLength(1);
  expect(search).toHaveBeenLastCalledWith("An");
});

it("creates the Contact that no search found and links it to the Task", async () => {
  const user = userEvent.setup();
  const create = vi.fn().mockResolvedValue({ contact: bo });
  const link = vi.fn().mockResolvedValue({ linked: true });
  const list = vi
    .fn()
    .mockResolvedValueOnce({ items: [anna], next_cursor: null })
    .mockResolvedValue({ items: [anna, bo], next_cursor: null });
  render(
    rootTask(
      transport({
        createContact: create,
        linkContactToTask: link,
        listTaskContacts: list,
      }),
    ),
  );
  await user.type(await openSheet(user), "  Bo Berg ");
  expect(
    await screen.findByText(workEn.noContactMatches("Bo Berg")),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", {
      name: workEn.createAndLinkContact("Bo Berg"),
    }),
  );
  await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  expect(create).toHaveBeenCalledWith(
    { display_name: "Bo Berg" },
    expect.stringMatching(KEY),
  );
  expect(link).toHaveBeenCalledWith(
    taskA.id,
    bo.id,
    expect.stringMatching(KEY),
  );
  expect(
    await screen.findByRole("button", { name: bo.display_name }),
  ).toBeInTheDocument();
  // The list is read again and the sheet is closed.
  expect(screen.queryByLabelText(workEn.linkContact)).toBeNull();
});

it("links the created Contact on a retry instead of creating it again", async () => {
  const user = userEvent.setup();
  const create = vi.fn().mockResolvedValue({ contact: bo });
  const link = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("unavailable"))
    .mockResolvedValue({ linked: true });
  render(
    rootTask(transport({ createContact: create, linkContactToTask: link })),
  );
  await user.type(await openSheet(user), "Bo Berg");
  await user.click(
    await screen.findByRole("button", {
      name: workEn.createAndLinkContact("Bo Berg"),
    }),
  );
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(workEn.contactWriteFailed);
  await user.click(within(alert).getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(link).toHaveBeenCalledTimes(2));
  expect(create).toHaveBeenCalledTimes(1);
  expect(link.mock.calls[1]).toEqual(link.mock.calls[0]);
});

it("says a refused create in its own words and retries it with the same key", async () => {
  const user = userEvent.setup();
  const create = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("unavailable"))
    .mockResolvedValue({ contact: bo });
  render(rootTask(transport({ createContact: create })));
  await user.type(await openSheet(user), "Bo Berg");
  await user.click(
    await screen.findByRole("button", {
      name: workEn.createAndLinkContact("Bo Berg"),
    }),
  );
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(workEn.contactCreateFailed);
  await user.click(within(alert).getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
  expect(create.mock.calls[1]).toEqual(create.mock.calls[0]);
});

it("offers no create row when the host cannot create a Contact", async () => {
  const user = userEvent.setup();
  const work = transport({
    supportsTool: (name: string) => name !== "create_contact",
  });
  render(rootTask(work));
  await user.type(await openSheet(user), "Bo Berg");
  expect(
    await screen.findByText(workEn.noContactMatches("Bo Berg")),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", {
      name: workEn.createAndLinkContact("Bo Berg"),
    }),
  ).toBeNull();
});

it("closes on Escape and on ×, dropping the search, and returns the focus to + Link contact", async () => {
  const user = userEvent.setup();
  render(rootTask(transport()));
  await user.type(await openSheet(user), "Bo");
  await user.keyboard("{Escape}");
  expect(screen.queryByLabelText(workEn.linkContact)).toBeNull();
  const add = screen.getByRole("button", { name: workEn.linkContact });
  expect(add).toHaveFocus();

  await user.click(add);
  const input = screen.getByLabelText(workEn.linkContact);
  expect(input).toHaveValue("");
  await user.click(
    screen.getByRole("button", { name: workEn.closeContactSearch }),
  );
  expect(screen.queryByLabelText(workEn.linkContact)).toBeNull();
  expect(
    screen.getByRole("button", { name: workEn.linkContact }),
  ).toHaveFocus();
});

it("offers a retry when the search fails", async () => {
  const user = userEvent.setup();
  const search = vi
    .fn()
    .mockRejectedValueOnce(new HostToolError("unavailable"))
    .mockResolvedValue({ items: [erik], next_cursor: null });
  render(rootTask(transport({ searchContacts: search })));
  await user.type(await openSheet(user), "Erik");
  const alert = await screen.findByRole("alert");
  await user.click(within(alert).getByRole("button", { name: workEn.retry }));
  expect(
    await screen.findByRole("button", { name: erik.display_name }),
  ).toBeInTheDocument();
  expect(search).toHaveBeenLastCalledWith("Erik");
});

it("speaks Swedish: title, example, hint, empty sentence and create row", async () => {
  const user = userEvent.setup();
  render(
    <WorkView
      transport={transport()}
      initial={{ kind: "task", id: taskA.id }}
      labels={workSv}
    />,
  );
  const input = await openSheet(user, workSv);
  expect(screen.getByText("Koppla kontakt")).toBeInTheDocument();
  expect(input).toHaveAttribute("placeholder", "Sök på namn");
  expect(
    screen.getByText("Skriv minst två tecken för att söka."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Stäng" })).toBeInTheDocument();
  await user.type(input, "Gus");
  expect(
    await screen.findByText("Ingen kontakt matchar ”Gus”."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Skapa kontakt ”Gus”" }),
  ).toBeInTheDocument();
});

it("has the same link sheet labels in Swedish and English", () => {
  for (const key of [
    "contactSearchPlaceholder",
    "closeContactSearch",
    "contactAlreadyLinked",
  ] as const) {
    expect(workSv[key]).toBeTruthy();
    expect(workEn[key]).toBeTruthy();
    expect(workSv[key]).not.toBe(workEn[key]);
  }
  expect(workEn.createAndLinkContact("Gus")).toBe("Create contact “Gus”");
  expect(workSv.createAndLinkContact("Gus")).toBe("Skapa kontakt ”Gus”");
});
