import { expect, test } from "@playwright/test";
import { callTool, openRealApp, seed, uniqueTitle } from "./real-backend";

// Tags on the real server: the Agenda's tag filter reads the server again with the chosen tag, and a tag set from
// a task's page is stored as the task's whole tag set.

const yesterday = () => new Date(Date.now() - 36 * 3600 * 1000).toISOString();
const uniqueTag = () => `e2e${Math.random().toString(36).slice(2, 10)}`;

test("the Agenda's tag filter keeps only the tasks with that tag", async ({
  page,
}) => {
  const tag = uniqueTag();
  const tagged = uniqueTitle("Boka lokal");
  const plain = uniqueTitle("Handla kaffe");
  await seed("create_task", {
    title: tagged,
    due_at: yesterday(),
    tags: [tag],
  });
  await seed("create_task", { title: plain, due_at: yesterday() });

  const { app, failures } = await openRealApp(page, {
    tool: "get_work_agenda",
    locale: "en",
  });
  const row = (title: string) =>
    app.getByRole("button", { name: title, exact: true });
  await expect(row(plain)).toBeVisible();
  await app
    .getByRole("group", { name: "Filter by tag" })
    .getByRole("button", { name: tag })
    .click();
  await expect(row(tagged)).toBeVisible();
  await expect(row(plain)).toHaveCount(0);
  expect(failures).toEqual([]);
});

test("a tag set from a task's page is stored on the server", async ({
  page,
}) => {
  const tag = uniqueTag();
  const title = uniqueTitle("Skriv offert");
  const { task } = await seed<{ task: { id: string } }>("create_task", {
    title,
  });

  const { app, failures } = await openRealApp(page, {
    tool: "get_task",
    args: { task_id: task.id },
    locale: "en",
  });
  await app.getByRole("button", { name: "Add tag", exact: true }).click();
  await app.getByRole("textbox", { name: "New tag" }).fill(tag);
  await app.getByRole("textbox", { name: "New tag" }).press("Enter");
  await expect(
    app.getByRole("button", { name: `Remove tag ${tag}` }),
  ).toBeVisible();

  await expect
    .poll(async () => {
      const read = await callTool("get_task", { task_id: task.id });
      return (read.structuredContent?.task as { tags: string[] }).tags;
    })
    .toEqual([tag]);
  expect(failures).toEqual([]);
});
