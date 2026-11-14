import { expect, test } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { box, resolved, style } from "./computed-style";
import { settled } from "./mcp-host-fixture";
import {
  bigContactContext,
  bigContactList,
  fullTask,
  projectRecord,
  task,
  workReplies,
} from "./one-screen-fixtures";
import { ok } from "./sidekick-domain-fixtures";

// The Work room's contact and waiting views measured in a real Chromium from computed style and boxes. Simulated host
// (see mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture.

test("Contact editor: Save and Cancel are one sticky row resting on the foot reserve, as tall as its buttons plus 8 px over and under", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 360,
    theme: "light",
    tool: "get_contact_context",
    result: bigContactContext,
    replies: workReplies,
  });
  await settled(app);
  await app.getByRole("button", { name: "Fler val", exact: true }).click();
  await app.getByRole("button", { name: "Redigera", exact: true }).click();
  const row = app.locator(".work-actions-sticky");
  await expect(row).toBeVisible();
  expect(await style(row, "position", "bottom")).toEqual({
    position: "sticky",
    bottom: await resolved(app, "bottom", "var(--sk-foot-reserve)"),
  });
  expect(await style(row, "paddingTop", "paddingBottom")).toEqual({
    paddingTop: "8px",
    paddingBottom: "8px",
  });
  const buttons = await row.getByRole("button").all();
  expect(buttons).toHaveLength(2);
  const heights = await Promise.all(
    buttons.map(async (button) => (await box(button)).height),
  );
  expect((await box(row)).height).toBeCloseTo(Math.max(...heights) + 16, 0);
  expect(failures).toEqual([]);
});

test("Kontakter: a contact's name starts at the row's start edge, not centred", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 360,
    theme: "light",
    tool: "list_contacts",
    result: bigContactList,
    replies: workReplies,
  });
  await settled(app);
  const open = app.locator(".work-contact-list .sk-row-open").first();
  await expect(open).toBeVisible();
  expect(await style(open, "justifyContent", "textAlign")).toEqual({
    justifyContent: await resolved(app, "justify-content", "flex-start"),
    textAlign: "start",
  });
  const [button, text] = await Promise.all([
    box(open),
    open.evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const found = range.getBoundingClientRect();
      return { x: found.x, width: found.width };
    }),
  ]);
  expect(text.x - button.x).toBeLessThan(button.width / 4);
  expect(failures).toEqual([]);
});

function waiting(id: number, title: string, who: string | null, since: string) {
  return {
    kind: "task",
    id: `019f0000-0000-7000-8000-00000000f0${id}`,
    title,
    status: "todo",
    version: 2,
    agenda_group: "upcoming",
    waiting: true,
    waiting_since: since,
    waiting_on_contact_name: who,
  };
}

for (const width of [320, 500]) {
  test(`Waiting view at ${width} px: the reminder button is a 44 px target inside the row, and who and the days wrap instead of widening it`, async ({
    page,
  }) => {
    const items = [
      waiting(
        1,
        "Förbered demo för kunden i Göteborg",
        "Anna Berg-Lindqvist från ekonomiavdelningen",
        "2026-10-18T09:00:00+02:00",
      ),
      waiting(2, "Svar från banken", null, "2026-10-25T09:00:00+01:00"),
    ];
    const result = {
      items,
      filters: { waiting: "waiting" },
      next_cursor: null,
    };
    const { app, failures } = await openSidekick(page, {
      width,
      theme: "light",
      tool: "get_work_agenda",
      result,
      replies: { ...workReplies, get_work_agenda: ok(result) },
    });
    await settled(app);
    const row = app.locator(".work-waiting-row").first();
    await expect(row).toBeVisible();
    const remind = row.locator(".work-waiting-remind");
    await expect(remind).toBeVisible();
    const [rowBox, remindBox, who] = await Promise.all([
      box(row),
      box(remind),
      box(row.locator(".work-waiting-who")),
    ]);
    expect(remindBox.height).toBeGreaterThanOrEqual(44);
    expect(remindBox.width).toBeGreaterThanOrEqual(44);
    expect(remindBox.x + remindBox.width).toBeLessThanOrEqual(
      rowBox.x + rowBox.width + 0.5,
    );
    expect(who.x + who.width).toBeLessThanOrEqual(
      rowBox.x + rowBox.width + 0.5,
    );
    expect(
      await row.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
    expect(failures).toEqual([]);
  });
}

test("Inline Task card: after Markera klar the Ångra button is a 44 px target", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_task",
    result: { task: { ...fullTask, status: "todo" } },
    displayMode: "inline",
    availableDisplayModes: ["inline"],
    replies: {
      ...workReplies,
      update_task: ok({
        task: { ...fullTask, status: "completed", version: 4 },
      }),
    },
  });
  await settled(app);
  await app.getByRole("button", { name: "Markera klar", exact: true }).click();
  const undo = app.getByRole("button", { name: "Ångra", exact: true });
  await expect(undo).toBeVisible();
  await expect(undo).toBeFocused();
  expect((await box(undo)).height).toBeGreaterThanOrEqual(44);
  expect(failures).toEqual([]);
});

test("Contact page: a section heading takes its space from the section tokens, and the list under it has no 6 px margin of its own", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_contact_context",
    result: bigContactContext,
    replies: workReplies,
  });
  await settled(app);
  const heading = app.locator("article.work-contact h3").first();
  await expect(heading).toBeVisible();
  expect(await style(heading, "marginTop", "marginBottom")).toEqual({
    marginTop: await resolved(app, "margin-top", "var(--sk-section-above)"),
    marginBottom: await resolved(
      app,
      "margin-bottom",
      "var(--sk-section-below)",
    ),
  });
  const list = app.locator("article.work-contact h3 + .work-list").first();
  await expect(list).toBeVisible();
  expect((await style(list, "marginTop")).marginTop).not.toBe("6px");
  expect(failures).toEqual([]);
});

test("Project page: the Task rows are the shared agenda rows with no padding of their own, and a row without a meta line keeps its line in the middle of its 48 px", async ({
  page,
}) => {
  const rows = Array.from({ length: 3 }, (_, n) => ({
    ...task(n, "todo"),
    project_id: projectRecord.id,
    project_title: projectRecord.title,
    due_at: null,
    tags: [],
    priority: "normal",
  }));
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_project",
    result: { project: projectRecord },
    replies: {
      ...workReplies,
      list_tasks: ok({ tasks: rows, next_cursor: null }),
    },
  });
  await settled(app);
  const article = app.locator("article.work-project");
  await expect(article).toBeVisible();
  const row = article.locator(".work-list > li.work-agenda-row").first();
  await expect(row).toBeVisible();
  expect(
    await style(
      row,
      "paddingTop",
      "paddingRight",
      "paddingBottom",
      "paddingLeft",
    ),
  ).toEqual({
    paddingTop: "0px",
    paddingRight: "0px",
    paddingBottom: "0px",
    paddingLeft: "0px",
  });
  const line = row.locator(".work-agenda-line");
  await expect(line).toBeVisible();
  await expect(line.locator(".work-card-meta")).toHaveCount(0);
  // The row's own pad is 6 px plus the air the type scale adds, so the title sits in the middle of the 48 px.
  const [rowBox, titleBox] = await Promise.all([
    box(row),
    box(line.locator(".work-agenda-body > button").first()),
  ]);
  expect(rowBox.height).toBeGreaterThanOrEqual(48);
  expect(
    Math.abs(titleBox.y + titleBox.height / 2 - (rowBox.y + rowBox.height / 2)),
  ).toBeLessThan(3);
  expect(failures).toEqual([]);
});
