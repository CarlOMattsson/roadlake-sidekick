import { expect, test } from "@playwright/test";
import { callTool, openRealApp, seed, uniqueTitle } from "./real-backend";

// A task made on the server shows in the Agenda, and finishing it in the app is a write the server accepts:
// the version and idempotency key the app sends are the ones update_task requires.

test("a task made on the server shows in the Agenda and is finished from its page", async ({
  page,
}) => {
  const title = uniqueTitle("Ring tandläkaren");
  const yesterday = new Date(Date.now() - 36 * 3600 * 1000).toISOString();
  const { task } = await seed<{ task: { id: string } }>("create_task", {
    title,
    due_at: yesterday,
  });

  const { app, failures } = await openRealApp(page, {
    tool: "get_work_agenda",
  });
  const row = app.getByRole("button", { name: title, exact: true });
  await expect(row).toBeVisible();

  await row.click();
  await expect(
    app.getByRole("heading", { level: 2, name: title }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Markera klar" }).click();

  await expect
    .poll(async () => {
      const read = await callTool("get_task", { task_id: task.id });
      return (read.structuredContent?.task as { status: string }).status;
    })
    .toBe("completed");
  expect(failures).toEqual([]);
});
