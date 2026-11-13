import { expect, test } from "@playwright/test";
import {
  callTool,
  findTaskByTitle,
  openRealApp,
  seed,
  uniqueTitle,
} from "./real-backend";

// Writes the app makes on a Task, with the server as the judge: a Task and a Step made in the app are stored,
// a Step checked off is completed there, and a Task changed elsewhere in the meantime is refused and read again.

test("a task made in the Agenda is listed there and stored on the server", async ({
  page,
}) => {
  const title = uniqueTitle("Boka lokal");

  const { app, failures } = await openRealApp(page, {
    tool: "get_work_agenda",
    locale: "en",
  });
  await app.getByRole("button", { name: "New task", exact: true }).click();
  const field = app.getByRole("textbox", { name: "New task", exact: true });
  await field.fill(title);
  await app.getByRole("button", { name: "Add task", exact: true }).click();
  await expect(
    app
      .getByRole("region", { name: /^Just added/ })
      .getByText(title, { exact: true }),
  ).toBeVisible();

  await expect
    .poll(async () => (await findTaskByTitle(title))?.status)
    .toBe("todo");
  expect(failures).toEqual([]);
});

test("a Step added to a task and checked off in the app is completed on the server", async ({
  page,
}) => {
  const title = uniqueTitle("Flytta kontoret");
  const step = uniqueTitle("Hyr bil");
  const { task } = await seed<{ task: { id: string } }>("create_task", {
    title,
  });

  const { app, failures } = await openRealApp(page, {
    tool: "get_task",
    args: { task_id: task.id },
    locale: "en",
  });
  await app.getByRole("button", { name: "Add step", exact: true }).click();
  await app.getByLabel("Step name").fill(step);
  await app.getByRole("button", { name: "Add step" }).click();
  const box = app.getByRole("checkbox", { name: step });
  await expect(box).toBeVisible();

  const stored = async () => {
    const read = await callTool("list_task_steps", { task_id: task.id });
    return (
      read.structuredContent?.items as { title: string; status: string }[]
    ).map((item) => [item.title, item.status]);
  };
  await expect.poll(stored).toEqual([[step, "todo"]]);

  await box.click();
  await expect(box).toBeChecked();
  await expect.poll(stored).toEqual([[step, "completed"]]);
  expect(failures).toEqual([]);
});

test("a task changed on the server after it was read is refused, shown as a conflict and read again", async ({
  page,
}) => {
  const title = uniqueTitle("Skicka offert");
  const changed = uniqueTitle("Skicka reviderad offert");
  const { task } = await seed<{ task: { id: string; version: number } }>(
    "create_task",
    { title },
  );

  const { app, failures } = await openRealApp(page, {
    tool: "get_task",
    args: { task_id: task.id },
    locale: "en",
  });
  await expect(
    app.getByRole("heading", { level: 2, name: title, exact: true }),
  ).toBeVisible();

  // Someone else renames the task after the app read it: the version the app holds is now one behind.
  await seed("update_task", {
    task_id: task.id,
    version: task.version,
    changes: { title: changed },
  });

  await app.getByRole("button", { name: "Mark as done", exact: true }).click();
  const banner = app.getByRole("alert");
  await expect(banner).toContainText("This task was changed elsewhere");
  await expect(banner).toBeFocused();
  const refused = await callTool("get_task", { task_id: task.id });
  expect((refused.structuredContent?.task as { status: string }).status).toBe(
    "todo",
  );

  await banner.getByRole("button", { name: "Refresh" }).click();
  await expect(app.getByRole("alert")).toHaveCount(0);
  await expect(
    app.getByRole("heading", { level: 2, name: changed, exact: true }),
  ).toBeVisible();

  // Read again, the app holds the current version and the same action now goes through.
  await app.getByRole("button", { name: "Mark as done", exact: true }).click();
  await expect
    .poll(async () => {
      const read = await callTool("get_task", { task_id: task.id });
      return (read.structuredContent?.task as { status: string }).status;
    })
    .toBe("completed");
  expect(failures).toEqual([]);
});
