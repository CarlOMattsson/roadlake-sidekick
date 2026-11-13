import { expect, test } from "@playwright/test";
import { callTool, openRealApp, seed, uniqueTitle } from "./real-backend";

// The shopping list on the real server: an item typed into the list is stored, and ticking an item is a
// purchase the server records with the version the app read.

type Item = { id: string; name: string; purchased: boolean };
type ListDetail = { shopping_list: { id: string }; items: Item[] };

async function serverItems(listId: string): Promise<Item[]> {
  const read = await callTool("get_shopping_list", { list_id: listId });
  return (read.structuredContent as unknown as ListDetail).items;
}

test("an item added in the list is stored and a ticked item is recorded as bought", async ({
  page,
}) => {
  const { shopping_list: list } = await seed<{ shopping_list: { id: string } }>(
    "create_shopping_list",
    { name: uniqueTitle("Veckohandling") },
  );
  const milk = uniqueTitle("Mjölk");
  const bread = uniqueTitle("Bröd");
  await seed("add_shopping_items", {
    list_id: list.id,
    items: [{ name: milk, client_ref: "0" }],
  });

  const { app, failures } = await openRealApp(page, {
    tool: "get_shopping_list",
    args: { list_id: list.id },
    locale: "en",
  });
  await expect(app.getByText(milk, { exact: true })).toBeVisible();

  await app.getByRole("button", { name: "Add item", exact: true }).click();
  const addField = app.getByRole("textbox").first();
  await addField.fill(bread);
  await addField.press("Enter");
  await expect(app.getByText(bread, { exact: true })).toBeVisible();
  await expect
    .poll(async () => (await serverItems(list.id)).map((item) => item.name))
    .toContain(bread);

  await app.getByRole("button", { name: `Mark ${milk} as bought` }).click();
  await expect
    .poll(
      async () =>
        (await serverItems(list.id)).find((item) => item.name === milk)
          ?.purchased,
    )
    .toBe(true);
  expect(failures).toEqual([]);
});
