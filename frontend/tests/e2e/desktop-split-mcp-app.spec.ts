import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { chooseView, goRoom, openSidekick } from "./app-navigation-fixtures";
import { box } from "./computed-style";
import {
  setHostContext,
  settled,
  simulatedHostState,
} from "./mcp-host-fixture";
import {
  bigAgenda,
  fullTask,
  journalReplies,
  uid,
  workReplies,
} from "./one-screen-fixtures";

// The list and the record beside it (desktop spec 2.1) in a real Chromium: at 1440 a row opens its record
// beside the list, a step through the list swaps it without a new layer, the unsaved guard asks first, Esc gives the
// focus back to the row, and Status opens a drawer over its columns. At 1023 and 390 the record is drawn alone, as
// before. SIMULATED host only (mcp-host-fixture.ts: every tool answer is a fixture); this is not a run in a real
// Claude or Android host.

// Each Task reads with its own title, so the detail shows which row it is.
const taskReplies = {
  get_task: {
    __byArgument: {
      key: "task_id",
      answers: Object.fromEntries(
        bigAgenda.items.map((item) => [
          item.id,
          {
            structuredContent: {
              task: { ...fullTask, id: item.id, title: item.title },
            },
          },
        ]),
      ),
    },
  },
};
const replies = { ...workReplies, ...journalReplies, ...taskReplies };

async function open(page: Page, width: number, height = 900) {
  await page.clock.setFixedTime(new Date("2026-11-03T12:00:00Z"));
  const opened = await openSidekick(page, {
    width,
    height,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    replies,
    platform: width >= 1024 ? "desktop" : "mobile",
  });
  await settled(opened.app);
  return opened;
}

type Item = { id: string; title: string };
const itemOf = (task: { id: string; title?: string }): Item => ({
  id: task.id,
  title: task.title ?? "",
});
const first = itemOf(bigAgenda.items[0]!);
const second = itemOf(bigAgenda.items[1]!);
const later = itemOf(bigAgenda.items[14]!);

const row = (app: FrameLocator, id: string, view = "task", room = "work") =>
  app.locator(`[data-sk-record="${room}:${view}:${id}"]`);
const openRow = (app: FrameLocator, item: Item) =>
  row(app, item.id)
    .getByRole("button", { name: item.title, exact: true })
    .click();
const pane = (app: FrameLocator, kind: string) =>
  app.locator(`[data-room='work'] [data-pane='${kind}']`);
const detailTitle = (app: FrameLocator, title: string) =>
  pane(app, "detail").getByRole("heading", { level: 2, name: title });
const workLayers = (app: FrameLocator) =>
  app.locator("[data-room='work'] .sk-rooms__layer");

const pageScroll = (app: FrameLocator) =>
  app
    .locator("html")
    .evaluate(() => Math.round(document.scrollingElement?.scrollTop ?? 0));
const scrollTo = (app: FrameLocator, y: number) =>
  app.locator("html").evaluate((_, top) => {
    document.scrollingElement!.scrollTop = top;
  }, y);
/** The `data-sk-record` of the row that holds the focus, or null. */
const focusedRow = (app: FrameLocator) =>
  app
    .locator("html")
    .evaluate(
      () =>
        document.activeElement
          ?.closest("[data-sk-record]")
          ?.getAttribute("data-sk-record") ?? null,
    );

/** The Task whose row is the current one (`aria-current`): j steps in the order the list draws, not the fixture's. */
async function currentItem(app: FrameLocator): Promise<Item> {
  const current = app.locator(
    "[data-room='work'] [data-pane='list'] [data-sk-record][aria-current='true']",
  );
  await expect(current).toHaveCount(1);
  const id = (await current.getAttribute("data-sk-record"))!.split(":")[2];
  return itemOf(bigAgenda.items.find((item) => item.id === id)!);
}

/** The shell's model-context lines that name the record with `id`. */
async function linesAbout(page: Page, id: string) {
  const { modelContexts } = await simulatedHostState(page);
  return modelContexts.filter((line) => line.includes(`(id ${id})`));
}

test.describe("at 1440", () => {
  test("a row opens its record beside the list; j swaps it in place; Esc closes it and the focus is on the row", async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await open(page, 1440);
    const split = app.locator("[data-room='work'] .sk-split");
    await expect(split).toHaveAttribute("data-split", "aside");
    // Nothing open: the hints stand where the record will.
    await expect(app.locator(".sk-detail-hints")).toBeVisible();
    await expect(app.locator(".sk-detail-hints")).toContainText("Välj rad");

    await openRow(app, first);
    await expect(split).toHaveAttribute("data-split", "split");
    await expect(detailTitle(app, first.title)).toBeVisible();
    await settled(app);
    const list = await box(pane(app, "list"));
    const detail = await box(pane(app, "detail"));
    expect(list.x).toBeCloseTo(104, 0);
    expect(list.x + list.width).toBeCloseTo(524, 0);
    expect(detail.x).toBeCloseTo(580, 0);
    // A click leaves the list where it was.
    expect(await pageScroll(app)).toBe(0);
    await expect(row(app, first.id)).toHaveAttribute("aria-current", "true");
    // The shell's Back row is not drawn: the detail's head has the × instead.
    await expect(app.locator(".sk-rooms__bar .sk-back-header")).toHaveCount(0);
    await expect(
      pane(app, "detail").getByRole("button", { name: "Stäng uppgiften" }),
    ).toHaveAttribute("aria-keyshortcuts", "Escape");

    // j: the next row's record takes the place, the stack's depth stays the same.
    const layers = await workLayers(app).count();
    await page.keyboard.press("j");
    await expect(row(app, first.id)).not.toHaveAttribute("aria-current");
    const next = await currentItem(app);
    await expect(detailTitle(app, next.title)).toBeVisible();
    expect(await workLayers(app).count()).toBe(layers);
    await expect(split).toHaveAttribute("data-swapped");

    // The model was told once per record opened.
    await expect.poll(() => linesAbout(page, next.id)).toHaveLength(1);
    expect(await linesAbout(page, first.id)).toHaveLength(1);

    // Esc closes the record without moving the list (j kept its row in view), and the row has the focus.
    const scrolled = await pageScroll(app);
    await page.keyboard.press("Escape");
    await expect(split).toHaveAttribute("data-split", "aside");
    expect(await focusedRow(app)).toBe(`work:task:${next.id}`);
    await expect(row(app, next.id)).toHaveAttribute("aria-current", "true");
    expect(await pageScroll(app)).toBe(scrolled);
    expect(failures).toEqual([]);
    expect(networkRequests()).toBe(0);
  });

  test("a row far down opens its record in view, and the list keeps its scroll through open and close", async ({
    page,
  }) => {
    const { app, failures } = await open(page, 1440);
    await scrollTo(app, 400);
    await openRow(app, later);
    await expect(detailTitle(app, later.title)).toBeVisible();
    await settled(app);
    expect(await pageScroll(app)).toBe(400);
    // The record's head is in the window, under the bar, though the record is taller than the window.
    const head = await box(detailTitle(app, later.title));
    expect(head.y).toBeGreaterThan(40);
    expect(head.y).toBeLessThan(300);
    await page.keyboard.press("Escape");
    await expect(app.locator("[data-room='work'] .sk-split")).toHaveAttribute(
      "data-split",
      "aside",
    );
    expect(await pageScroll(app)).toBe(400);
    expect(await focusedRow(app)).toBe(`work:task:${later.id}`);
    expect(failures).toEqual([]);
  });

  test("the unsaved guard asks before a click or j drops an edit in the record beside the list", async ({
    page,
  }) => {
    const { app, failures } = await open(page, 1440);
    await openRow(app, first);
    await expect(detailTitle(app, first.title)).toBeVisible();
    await settled(app);
    const detail = pane(app, "detail");
    await detail.getByRole("button", { name: "Fler val", exact: true }).click();
    await app.getByRole("button", { name: "Redigera" }).click();
    await detail.getByLabel("Titel").fill("Ring Anna i morgon");

    // A click on another row asks; Fortsätt redigera keeps the edit.
    await openRow(app, second);
    await expect(app.getByText("Släng ändringarna?")).toBeVisible();
    await app.getByRole("button", { name: "Fortsätt redigera" }).click();
    await expect(detail.getByLabel("Titel")).toHaveValue("Ring Anna i morgon");
    await expect(row(app, first.id)).toHaveAttribute("aria-current", "true");

    // j from outside the field asks too; Släng swaps the record.
    await detail.getByLabel("Titel").blur();
    await page.keyboard.press("j");
    await expect(app.getByText("Släng ändringarna?")).toBeVisible();
    await app.getByRole("button", { name: "Släng", exact: true }).click();
    await expect(row(app, first.id)).not.toHaveAttribute("aria-current");
    await expect(
      detailTitle(app, (await currentItem(app)).title),
    ).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("Status opens a record as a drawer of 440 over the columns, which do not move", async ({
    page,
  }) => {
    const { app, failures } = await open(page, 1440);
    await chooseView(app, "Status", 1440);
    await settled(app);
    // The columns of the board, not the drawer's sections.
    const xs = () =>
      app
        .locator("[data-room='work']")
        .getByRole("region")
        .evaluateAll((sections) =>
          sections
            .filter((section) => !section.closest("[data-pane='drawer']"))
            .map((section) => Math.round(section.getBoundingClientRect().x)),
        );
    const before = await xs();
    expect(before.length).toBeGreaterThan(1);
    const card = app
      .getByRole("region", { name: "Pågår" })
      .locator("[data-sk-record]")
      .first();
    const record = await card.getAttribute("data-sk-record");
    await card.locator("[data-sk-open]").click();
    const drawer = pane(app, "drawer");
    await expect(drawer).toBeVisible();
    await settled(app);
    expect((await box(drawer)).width).toBeCloseTo(440, 0);
    expect(await xs()).toEqual(before);
    // A click leaves the focus on the card, as on a list's row.
    expect(await focusedRow(app)).toBe(record);
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    expect(await focusedRow(app)).toBe(record);
    expect(failures).toEqual([]);
  });

  test("a Contact and a Journal entry open beside their lists too", async ({
    page,
  }) => {
    const { app, failures } = await open(page, 1440);
    await goRoom(app, "Kontakter");
    await settled(app);
    const bo = uid(4, 1);
    await app
      .locator(`[data-sk-record="contacts:contact:${bo}"] [data-sk-open]`)
      .click();
    const contacts = app.locator("[data-room='contacts'] .sk-split");
    await expect(contacts).toHaveAttribute("data-split", "split");
    await expect(
      app.locator("[data-room='contacts'] [data-pane='detail']"),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(contacts).toHaveAttribute("data-split", "aside");
    expect(await focusedRow(app)).toBe(`contacts:contact:${bo}`);

    await goRoom(app, "Dagbok");
    await settled(app);
    await app
      .getByRole("button", { name: /Lunch med Bo/ })
      .first()
      .click();
    await expect(
      app.locator("[data-room='journal'] .sk-split"),
    ).toHaveAttribute("data-split", "split");
    await expect(
      app.locator("[data-room='journal'] [data-pane='detail']"),
    ).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("the detail scrolls by itself only where the host fixes the height", async ({
    page,
  }) => {
    const { app, failures } = await open(page, 1440);
    await openRow(app, first);
    await expect(detailTitle(app, first.title)).toBeVisible();
    await settled(app);
    const bound = () =>
      pane(app, "detail").evaluate((element) => {
        const style = getComputedStyle(element);
        return { maxHeight: style.maxHeight, overflowY: style.overflowY };
      });
    // A height the app's size decides (the default here): no bound, the page scrolls.
    expect(await bound()).toEqual({ maxHeight: "none", overflowY: "visible" });

    await setHostContext(page, {
      containerDimensions: { width: 1440, height: 900 },
    });
    await expect(app.locator("html")).toHaveAttribute(
      "data-host-height",
      "fixed",
    );
    await settled(app);
    const fixed = await bound();
    expect(fixed.overflowY).toBe("auto");
    expect(Number.parseFloat(fixed.maxHeight)).toBeLessThan(900);
    const detail = await box(pane(app, "detail"));
    expect(detail.y + detail.height).toBeLessThanOrEqual(900);
    expect(failures).toEqual([]);
  });
});

for (const width of [1023, 390]) {
  test(`at ${width}: the record is drawn alone with the Back row, and Back returns to the list where it was`, async ({
    page,
  }) => {
    const { app, failures } = await open(page, width, width > 400 ? 900 : 780);
    const split = app.locator("[data-room='work'] .sk-split");
    await expect(split).toHaveAttribute("data-split", "single");
    await expect(app.locator(".sk-detail-hints")).toHaveCount(0);
    await scrollTo(app, 300);
    await row(app, later.id).scrollIntoViewIfNeeded();
    const at = await pageScroll(app);
    expect(at).toBeGreaterThan(0);
    await openRow(app, later);
    const heading = app.getByRole("heading", { level: 2, name: later.title });
    await expect(heading).toBeVisible();
    await expect(split).toHaveAttribute("data-split", "single");
    await expect(app.locator("[data-room='work'] [data-pane]")).toHaveCount(0);
    const back = app.locator(".sk-rooms__bar .sk-back-header button").first();
    await expect(back).toBeVisible();
    // Esc is the host's here: it does not close the record.
    await page.keyboard.press("Escape");
    await expect(heading).toBeVisible();
    await back.click();
    await expect(row(app, later.id)).toBeVisible();
    await expect.poll(() => pageScroll(app)).toBe(at);
    await expect.poll(() => linesAbout(page, later.id)).toHaveLength(1);
    expect(failures).toEqual([]);
  });
}
