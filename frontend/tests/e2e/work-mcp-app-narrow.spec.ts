import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import { test, expect } from "@playwright/test";

// Narrow fullscreen frames (190 px and 375 px frames). On a narrow frame the agenda row stacks, so the title
// keeps its width; the meta line wraps and keeps the priority and the due date whole; a task detail with an
// unbroken step title keeps the page inside the frame. The data is a fixture on the simulated host.
const fullscreenHost = {
  locale: "sv",
  theme: "light",
  displayMode: "fullscreen",
  availableDisplayModes: ["inline", "fullscreen"],
};
const dayMs = 24 * 60 * 60 * 1000;
const narrowTaskId = "019f0000-0000-7000-8000-0000000000b1";
const narrowTask = {
  kind: "task",
  id: narrowTaskId,
  title: "Skicka faktura till Bergström Bygg AB för oktober",
  status: "todo",
  priority: "high",
  due_at: new Date(Date.now() - dayMs).toISOString(),
  project_id: null,
  project_title: "Bokslut 2026 och årsredovisning",
  domain_accent: "blue",
  agenda_group: "overdue",
  version: 1,
};
const narrowAgenda = { items: [narrowTask], next_cursor: null };
const narrowTaskRecord = {
  id: narrowTaskId,
  project_id: null,
  domain_id: null,
  process_id: null,
  derived_domain_id: null,
  title: narrowTask.title,
  description: null,
  status: "todo",
  priority: "high",
  due_at: narrowTask.due_at,
  completed_at: null,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
  version: 1,
};

for (const width of [190, 375]) {
  test(`sandboxed Work agenda at ${width} px: no sideways scroll, a title wider than 100 px and a visible due date`, async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await openSimulatedApp(page, {
      resource: readBuiltApp("work"),
      width,
      height: 800,
      hostContext: fullscreenHost,
      replies: { get_work_agenda: { structuredContent: narrowAgenda } },
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, narrowAgenda);
    const row = app.locator(".work-agenda-row").first();
    const title = row.locator(".work-agenda-body > button");
    const due = row.locator(".work-card-due");
    await expect(title).toBeVisible();
    const titleBox = await title.boundingBox();
    expect(titleBox?.width ?? 0).toBeGreaterThan(100);
    await expect(due).toBeVisible();
    const dueBox = await due.boundingBox();
    expect((dueBox?.x ?? 0) + (dueBox?.width ?? 0)).toBeLessThanOrEqual(width);
    const dimensions = await app.locator("body").evaluate((body) => ({
      width: body.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
    expect(failures).toEqual([]);
    expect(networkRequests()).toBe(0);
  });
}

test("sandboxed Work task detail at 190 px: an unbroken step title stays inside the frame", async ({
  page,
}) => {
  const longStep = {
    id: "019f0000-0000-7000-8000-0000000000c1",
    task_id: narrowTaskId,
    title:
      "Bokföringsunderlagsnummerkontrollsdokumentationsförteckning-2026-10-30",
    status: "todo",
    position: 1,
    version: 1,
  };
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 190,
    height: 800,
    hostContext: fullscreenHost,
    replies: {
      get_work_agenda: { structuredContent: narrowAgenda },
      get_task: { structuredContent: { task: narrowTaskRecord } },
      list_task_steps: {
        structuredContent: { items: [longStep], next_cursor: null },
      },
      list_task_contacts: {
        structuredContent: { items: [], next_cursor: null },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, narrowAgenda);
  await app.locator(".work-agenda-body > button").first().click();
  const step = app.locator(".work-steps label > span");
  await expect(step).toHaveText(longStep.title);
  const stepBox = await step.boundingBox();
  expect((stepBox?.x ?? 0) + (stepBox?.width ?? 0)).toBeLessThanOrEqual(190);
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

// When the tabs do not fit (320 px, 190 px) the tab row is hidden and the view picker "Agenda ⌄" stands in its
// place; it opens a menu of menuitemradio with the chosen view checked. No label is cut.
for (const width of [320, 190]) {
  test(`sandboxed Work view picker at ${width} px replaces the hidden tabs: no label is cut`, async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await openSimulatedApp(page, {
      resource: readBuiltApp("work"),
      width,
      height: 800,
      hostContext: fullscreenHost,
      replies: { get_work_agenda: { structuredContent: narrowAgenda } },
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, narrowAgenda);
    const tabs = app.locator(".work-view-tabs__tab");
    await expect(tabs.first()).toBeHidden();
    const pick = app.locator(".work-view-pick");
    await expect(pick).toBeVisible();
    await expect(pick).toContainText("Agenda");
    const pickClipped = await pick.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    );
    expect(pickClipped).toBe(false);
    await pick.click();
    const views = app.getByRole("menuitemradio");
    expect(await views.count()).toBeGreaterThanOrEqual(2);
    await expect(
      app.getByRole("menuitemradio", { name: "Agenda", exact: true }),
    ).toHaveAttribute("aria-checked", "true");
    const clipped = await views.evaluateAll((elements) =>
      elements
        .filter((element) => element.scrollWidth > element.clientWidth)
        .map((element) => element.textContent ?? ""),
    );
    expect(clipped).toEqual([]);
    const dimensions = await app.locator("body").evaluate((body) => ({
      width: body.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
    expect(failures).toEqual([]);
    expect(networkRequests()).toBe(0);
  });
}

// One card, one screen: a host that offers no fullscreen gets the agenda as a summary inline. Show all expands the
// whole agenda inline, and the app asks the host for no fullscreen (displayModeRequests stays empty).
test("sandboxed Work agenda without fullscreen: the inline card is a summary, Show all expands all 25 records inline", async ({
  page,
}) => {
  const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const items = Array.from({ length: 25 }, (_, index) => ({
    kind: "task",
    id: `019f0000-0000-7000-8000-${String(index + 1).padStart(12, "0")}`,
    title: `Förfallen uppgift ${index + 1}`,
    status: "todo",
    priority: "normal",
    due_at: dayAgo,
    project_id: null,
    project_title: null,
    domain_accent: "blue",
    agenda_group: "overdue",
    version: 1,
  }));
  const agenda = { items, next_cursor: null };
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 750,
    hostContext: {
      locale: "sv",
      theme: "light",
      availableDisplayModes: ["inline"],
    },
    replies: { get_work_agenda: { structuredContent: agenda } },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, agenda);
  // Inline: the kicker names the day, the title carries the counts, the first row and at most two more
  // overdue rows, not the 25 records.
  await expect(app.locator(".work-compact-kind")).toHaveText(/^Arbete · /);
  await expect(app.locator(".work-compact-title")).toHaveText("25 försenade");
  await expect(app.locator(".work-compact-row")).toHaveCount(3);
  await expect(app.locator(".work-agenda-row")).toHaveCount(0);
  await app.getByRole("button", { name: /^Öppna Agenda/ }).click();
  await expect(app.locator(".work-agenda-row")).toHaveCount(25);
  await expect(app.locator(".work-compact-row")).toHaveCount(0);
  expect((await simulatedHostState(page)).displayModeRequests).toEqual([]);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("sandboxed Work agenda creates a Task from the new-Task row through the host and shows it at once", async ({
  page,
}) => {
  const createdTask = {
    id: "019f0000-0000-7000-8000-0000000000e1",
    title: "Ring Anna fredag",
    status: "todo",
    due_at: null,
    version: 1,
    project_id: null,
    domain_id: null,
  };
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 800,
    hostContext: fullscreenHost,
    replies: {
      get_work_agenda: { structuredContent: narrowAgenda },
      list_tasks: { structuredContent: { tasks: [], next_cursor: null } },
      create_task: { structuredContent: { task: createdTask } },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, narrowAgenda);
  // No create field stands open at rest: the "+" in the tab row ("Ny uppgift") unfolds it, with the focus in it.
  const field = app.getByRole("textbox", { name: "Ny uppgift", exact: true });
  await expect(field).toHaveCount(0);
  await app.getByRole("button", { name: "Ny uppgift", exact: true }).click();
  await expect(field).toBeFocused();
  await expect(field).toHaveAttribute(
    "placeholder",
    "Ny uppgift, t.ex. ring Anna",
  );
  // Empty field: the 48 x 48 px square is × "Stäng" (closes the field), not "+".
  const close = app.getByRole("button", { name: "Stäng", exact: true });
  await expect(close).toHaveClass(/sk-createfield__btn/);
  await expect(close).not.toHaveClass(/sk-createfield__btn--add/);
  const closeBox = await close.boundingBox();
  expect(closeBox?.width).toBe(48);
  expect(closeBox?.height).toBe(48);
  expect(
    (await simulatedHostState(page)).calls.filter(
      (call) => call.name === "create_task",
    ),
  ).toEqual([]);
  await field.fill("Ring Anna fredag");
  // With text the same square is "+" (the primary), named "Lägg till uppgift".
  const add = app.getByRole("button", {
    name: "Lägg till uppgift",
    exact: true,
  });
  await expect(add).toHaveClass(/sk-createfield__btn--add/);
  const addBox = await add.boundingBox();
  expect(addBox?.width).toBe(48);
  expect(addBox?.height).toBe(48);
  await add.click();
  const group = app.getByRole("region", { name: "Nyss tillagda (1)" });
  await expect(
    group.getByText("Ring Anna fredag", { exact: true }),
  ).toBeVisible();
  await expect(group.getByText("Utan datum", { exact: true })).toBeVisible();
  // Enter or + empties the field and keeps the focus in it, so several Tasks can be typed in a row.
  await expect(field).toHaveValue("");
  await expect(field).toBeFocused();
  const create = (await simulatedHostState(page)).calls.filter(
    (call) => call.name === "create_task",
  );
  expect(create).toHaveLength(1);
  // The title only: no date is read out of "fredag", and no Project is sent.
  expect(Object.keys(create[0]!.arguments).sort()).toEqual([
    "idempotency_key",
    "title",
  ]);
  expect(create[0]!.arguments.title).toBe("Ring Anna fredag");
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

// The date input lies over the "Välj datum …" chip; a chosen date closes the menu
// and removes the input, and focus goes to a control that stays. A simulated host, not a real Claude or Android one.
test("sandboxed Work agenda at 360 px and 200 % text: the date input takes focus, and focus stays in the row after a date is chosen", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 800,
    hostContext: fullscreenHost,
    replies: {
      get_work_agenda: { structuredContent: narrowAgenda },
      update_task: {
        structuredContent: {
          task: {
            ...narrowTaskRecord,
            due_at: "2030-01-15T22:59:59Z",
            version: 2,
          },
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, narrowAgenda);
  await app.locator("html").evaluate((root) => {
    root.style.fontSize = "32px";
  });
  const row = app.locator(".work-agenda-row").first();
  await row
    .locator(".work-agenda-body > button")
    .dispatchEvent("contextmenu", undefined, { timeout: 8000 });
  await row.getByRole("button", { name: /^Datum/ }).click();
  // "Välj datum …" is the date input itself, laid invisibly over its chip (no chip to press first).
  const field = row.getByLabel("Välj datum", { exact: true });
  await expect(field).toHaveCount(1);
  // It holds the Task's own date, so the platform's picker opens on it.
  await expect(field).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await field.focus();
  await expect(field).toBeFocused();
  await field.fill("2030-01-15");
  // The move closes the menu and the input goes with it; focus is on a control of the row (the ring or the title),
  // not on the body.
  await expect(field).toHaveCount(0);
  await expect(row.locator(":focus")).toHaveCount(1);
  const focused = await app
    .locator("body")
    .evaluate(() => document.activeElement?.tagName ?? "");
  expect(focused).toBe("BUTTON");
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

// While a row's menu is open at large text, only the ordinary meta line is hidden. Ångra and the
// receipt stay in sight and can be pressed.
test("sandboxed Work agenda at 360 px and 200 % text: Ångra stays visible and pressable while the row menu is open", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 800,
    hostContext: fullscreenHost,
    replies: {
      get_work_agenda: { structuredContent: narrowAgenda },
      update_task: {
        structuredContent: {
          task: { ...narrowTaskRecord, status: "in_progress", version: 2 },
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, narrowAgenda);
  await app.locator("html").evaluate((root) => {
    root.style.fontSize = "32px";
  });
  const row = app.locator(".work-agenda-row").first();
  const title = row.locator(".work-agenda-body > button");
  await title.dispatchEvent("contextmenu", undefined, { timeout: 8000 });
  await row.getByRole("button", { name: "Pågår", exact: true }).click();
  const undo = row.getByRole("button", { name: "Ångra" });
  await expect(undo).toBeVisible();
  // The menu is closed by the write; open it again on the row that carries the Ångra.
  await row
    .locator(".work-agenda-body > button")
    .dispatchEvent("contextmenu", undefined, { timeout: 8000 });
  await expect(row.locator(".work-agenda-menu")).toBeVisible();
  await expect(row.getByRole("status")).toBeVisible();
  await expect(undo).toBeVisible();
  const box = await undo.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(40);
  await undo.click();
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});
