import { expect, test } from "@playwright/test";
import { callTool, openRealApp, seed, uniqueTitle } from "./real-backend";

// A Contact made on the server is opened in the app; a nickname and a tag set there are stored by the server,
// each against the version the app read.

type StoredContact = {
  version: number;
  aliases: { value: string }[];
  tags: string[];
};

async function storedContact(contactId: string): Promise<StoredContact> {
  const read = await callTool("get_contact_context", {
    contact_id: contactId,
  });
  return read.structuredContent?.contact as StoredContact;
}

test("a nickname and a tag set on a Contact's page are stored on the server", async ({
  page,
}) => {
  const name = uniqueTitle("Anna Andersson");
  const nickname = uniqueTitle("Annan");
  const tag = `e2e${Math.random().toString(36).slice(2, 10)}`;
  const { contact } = await seed<{ contact: { id: string } }>(
    "create_contact",
    { display_name: name },
  );

  const { app, failures } = await openRealApp(page, {
    tool: "get_contact_context",
    args: { contact_id: contact.id },
    locale: "en",
  });
  await expect(
    app.getByRole("heading", { level: 2, name, exact: true }),
  ).toBeVisible();

  // Nicknames are edited in the editor, in the "Nicknames" group.
  await app.getByRole("button", { name: "More options", exact: true }).click();
  await app.getByRole("button", { name: "Edit", exact: true }).click();
  const nicknames = app.getByRole("group", { name: "Nicknames" });
  await nicknames.getByLabel("New nickname", { exact: true }).fill(nickname);
  await nicknames
    .getByRole("button", { name: "Add nickname", exact: true })
    .click();
  await expect(
    nicknames.getByRole("button", { name: `Remove nickname ${nickname}` }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Cancel", exact: true }).click();

  await app.getByRole("button", { name: "Add tag", exact: true }).click();
  await app.getByRole("textbox", { name: "New tag" }).fill(tag);
  await app.getByRole("textbox", { name: "New tag" }).press("Enter");
  await expect(
    app.getByRole("button", { name: `Remove tag ${tag}` }),
  ).toBeVisible();

  await expect
    .poll(async () => {
      const stored = await storedContact(contact.id);
      return { aliases: stored.aliases.map((a) => a.value), tags: stored.tags };
    })
    .toEqual({ aliases: [nickname], tags: [tag] });
  expect(failures).toEqual([]);
});
