import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { callNames, openSidekick } from "./app-navigation-fixtures";
import { box } from "./computed-style";
import { task, workItem } from "./sidekick-domain-fixtures";

// The one menu (ui/menu.tsx) in a real Chromium against the simulated host (mcp-host-fixture.ts), not a real Claude or
// Android host. With a mouse (the desktop default here) the ⋯ menu and a row's context menu are popovers: 240 wide,
// right edge on the button's, 4 under it, nothing on the page moves; one Escape closes with the focus back on ⋯, and a
// press outside closes without a choice. A phone (the host reports a mobile platform) keeps the panel in the flow.

const agenda = { items: [workItem(task)], filters: {}, next_cursor: null };

async function openAgenda(
  page: Page,
  width: number,
  platform?: "mobile" | "desktop",
) {
  return openSidekick(page, {
    width,
    theme: "light",
    tool: "get_work_agenda",
    result: agenda,
    platform,
  });
}

const more = (app: FrameLocator) =>
  app.locator(".work-agenda-more button.work-tab-tool").first();
const openMenu = (app: FrameLocator) =>
  app.locator("[data-menu]:not([hidden])");
const rowTitle = (app: FrameLocator) =>
  app.getByRole("button", { name: task.title, exact: true });

test("⋯ in the agenda at 1280 px: a 240 popover under the button that moves nothing, keys move, one Escape closes on ⋯", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 1280, "desktop");
  const row = app.locator("li.work-agenda-row").first();
  await expect(row).toBeVisible();
  const rowBefore = await box(row);
  await more(app).click();
  const menu = openMenu(app);
  await expect(menu).toBeVisible();
  await expect(menu).toHaveAttribute("data-menu", "popover");
  expect(await menu.evaluate((m) => m.matches(":popover-open"))).toBe(true);
  const [menuBox, buttonBox] = await Promise.all([box(menu), box(more(app))]);
  expect(Math.abs(menuBox.width - 240)).toBeLessThanOrEqual(1);
  expect(
    Math.abs(menuBox.x + menuBox.width - (buttonBox.x + buttonBox.width)),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(menuBox.y - (buttonBox.y + buttonBox.height) - 4),
  ).toBeLessThanOrEqual(1);
  expect((await box(row)).y).toBe(rowBefore.y);
  // The focus starts on the first entry; ↓, End and Home move it.
  const entries = menu.locator("button:visible");
  const count = await entries.count();
  await expect(entries.first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(entries.nth(1)).toBeFocused();
  await page.keyboard.press("End");
  await expect(entries.nth(count - 1)).toBeFocused();
  await page.keyboard.press("Home");
  await expect(entries.first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(openMenu(app)).toHaveCount(0);
  await expect(more(app)).toBeFocused();
  expect(failures).toEqual([]);
});

test("⋯ in the agenda at 1280 px: a press outside closes the popover without a choice", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 1280, "desktop");
  await more(app).click();
  await expect(openMenu(app)).toBeVisible();
  const before = (await callNames(page)).length;
  // The empty side of the frame, left of the centred list: nothing there opens or chooses anything.
  await page.mouse.click(20, 600);
  await expect(openMenu(app)).toHaveCount(0);
  // Nothing was chosen: no call went out (Uppdatera would read the agenda again).
  expect((await callNames(page)).length).toBe(before);
  expect(failures).toEqual([]);
});

test("Shift+F10 on an agenda row at 1280 px opens its popover under the title, and Escape gives the title its focus back", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 1280, "desktop");
  const title = rowTitle(app);
  await title.focus();
  const row = app.locator("li.work-agenda-row").first();
  const rowBefore = await box(row);
  await page.keyboard.press("Shift+F10");
  const menu = openMenu(app);
  await expect(menu).toHaveAttribute("data-menu", "popover");
  const [menuBox, titleBox] = await Promise.all([box(menu), box(title)]);
  expect(Math.abs(menuBox.x - titleBox.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(menuBox.width - 240)).toBeLessThanOrEqual(1);
  // The row keeps its height: the menu is not in its flow.
  expect((await box(row)).height).toBe(rowBefore.height);
  await expect(menu.locator("button.sk-chip").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(openMenu(app)).toHaveCount(0);
  await expect(title).toBeFocused();
  expect(failures).toEqual([]);
});

test("⋯ in the agenda on a phone (390 px, mobile host): the panel in the flow under the tab row, as before", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 390, "mobile");
  await more(app).click();
  const menu = app.locator(".sk-menu-panel:not([hidden])");
  await expect(menu).toBeVisible();
  await expect(menu).toHaveAttribute("data-menu", "panel");
  await expect(menu).not.toHaveAttribute("popover");
  // In the flow: the list starts under the panel.
  const [menuBox, rowBox] = await Promise.all([
    box(menu),
    box(app.locator("li.work-agenda-row").first()),
  ]);
  expect(rowBox.y).toBeGreaterThan(menuBox.y + menuBox.height);
  expect(failures).toEqual([]);
});
