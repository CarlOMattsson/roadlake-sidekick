// Playwright runs this file outside Vitest. The host is simulated: it proves the layout in a sandboxed iframe, not in Claude or on Android.
import { test, expect, type Page } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import { sItem, sList } from "./one-screen-fixtures";

type Locale = "sv" | "en";

/** Set it to a folder to also write a screenshot of every case there. */
const SHOTS = process.env.SHOPPING_SHOTS_DIR;
const FREE_VERSION =
  '<meta name="sidekick-license" content=\'{"state":"unlicensed"}\'>';

const hostFor = (locale: Locale, displayMode: "inline" | "fullscreen") => ({
  locale,
  theme: "light",
  displayMode,
  availableDisplayModes: ["inline", "fullscreen"],
});

const batchOf = (count: number) => ({
  items: Array.from({ length: count }, (_, index) => ({
    item: sItem(index + 1, `Vara ${index + 1}`),
  })),
});

const hasNoSidewaysScroll = (page: Page) =>
  page
    .frameLocator("iframe")
    .locator("html")
    .evaluate((root) => root.scrollWidth <= root.clientWidth);

for (const locale of ["sv", "en"] as const) {
  for (const width of [320, 375]) {
    test(`the batch card's foot and license coin stay inside the card on ${width} px in ${locale}`, async ({
      page,
    }) => {
      const opened = await openSimulatedApp(page, {
        resource: readBuiltApp("shopping", locale).replace(
          "<head>",
          `<head>${FREE_VERSION}`,
        ),
        width,
        height: 700,
        hostContext: hostFor(locale, "inline"),
        replies: {},
      });
      await waitForAppInitialized(page);
      await deliverToolResult(page, batchOf(14));
      await settled(opened.app);
      const open = opened.app.getByRole("button", {
        name: /^(Öppna|Open) .*(11 fler tillagda|11 more added)/,
      });
      await expect(open).toBeVisible();
      const measure = await opened.app.locator("html").evaluate((root) => {
        const rect = (selector: string) =>
          document.querySelector(selector)!.getBoundingClientRect();
        return {
          scroll: root.scrollWidth,
          client: root.clientWidth,
          cardRight: rect(".sk-card").right,
          coinLeft: rect(".sk-license-mark").left,
          coinRight: rect(".sk-license-mark").right,
        };
      });
      expect(measure.scroll).toBeLessThanOrEqual(measure.client);
      // The coin stands inside the card, and the foot's words end before it begins.
      expect(measure.coinRight).toBeLessThanOrEqual(measure.cardRight);
      const box = (await open.boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(measure.coinLeft + 1);
      if (SHOTS)
        await page.screenshot({
          path: `${SHOTS}/batch-foot__${width}__${locale}.png`,
        });
      expect(opened.failures).toEqual([]);
    });
  }
}

/** The store view at 375 px with one plain item and one gift item with a named recipient. */
async function openStoreWithGift(page: Page, locale: Locale) {
  const milk = sItem(1, "Mjölk", { quantity: "2", unit: "l", store: "ICA" });
  const gift = sItem(2, "Bok", {
    store: "ICA",
    recipient_contact_id: "019f0000-0000-7000-8000-0000000000c1",
    recipient_contact_name: "Astrid Ek-Lindqvist",
  });
  const detail = {
    shopping_list: sList,
    items: [milk, gift],
    next_offset: null,
    evaluated_on: "2026-11-13",
  };
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("shopping", locale),
    width: 375,
    height: 800,
    hostContext: hostFor(locale, "fullscreen"),
    // No answer for the purchase: the write is refused.
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
      get_shopping_list: { structuredContent: detail },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, detail);
  await settled(opened.app);
  return opened;
}

for (const locale of ["sv", "en"] as const) {
  test(`a refused bought mark names the item and stands under its title, apart from its buttons, in ${locale}`, async ({
    page,
  }) => {
    const opened = await openStoreWithGift(page, locale);
    await opened.app
      .getByRole("button", {
        name:
          locale === "sv" ? "Markera Mjölk som köpt" : "Mark Mjölk as bought",
      })
      .click();
    const alert = opened.app.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(
      locale === "sv"
        ? "Det gick inte att markera ”Mjölk” som köpt."
        : "Couldn’t mark “Mjölk” as bought.",
    );
    await settled(opened.app);
    const place = await opened.app.locator("html").evaluate(() => {
      const row = document.querySelector(".shopping-store-item")!;
      const left = (selector: string) =>
        row.querySelector(selector)!.getBoundingClientRect().left;
      const [retry, refresh] = [
        ...row.querySelectorAll(".sk-error__actions button"),
      ].map((button) => button.getBoundingClientRect());
      return {
        name: left(".shopping-store-name"),
        message: left(".sk-error-message"),
        retry: retry!,
        refresh: refresh!,
      };
    });
    expect(place.message).toBeCloseTo(place.name, 0);
    // The buttons' touch boxes do not overlap, so a tap lands on the one it meant. Text buttons pull back their padding
    // with a negative margin, so the drawn boxes sit 12 px wider than the words on both sides.
    expect(place.refresh.left).toBeGreaterThanOrEqual(place.retry.right);
    if (SHOTS)
      await page.screenshot({
        path: `${SHOTS}/bocka-fel__375__${locale}.png`,
      });
    expect(await hasNoSidewaysScroll(page)).toBe(true);
    expect(opened.failures).toEqual([]);
  });

  test(`the gift recipient keeps its name, Change and Remove on one line and has one way out of the search in ${locale}`, async ({
    page,
  }) => {
    const opened = await openStoreWithGift(page, locale);
    await opened.app.getByRole("button", { name: /^Bok/ }).first().click();
    await opened.app
      .getByRole("button", { name: /^(Fler fält|More fields)/ })
      .click();
    const group = opened.app.getByRole("group", {
      name: locale === "sv" ? /^Presentmottagare/ : /^Gift recipient/,
    });
    await expect(group).toBeVisible();
    const buttons = group.locator(".shopping-recipient-current > button");
    await expect(buttons).toHaveCount(2);
    const name = (await group
      .locator(".shopping-recipient-name")
      .boundingBox())!;
    const change = (await buttons.nth(0).boundingBox())!;
    const remove = (await buttons.nth(1).boundingBox())!;
    // One line: the buttons share a top, Remove stands right of Change, and the name starts the line.
    expect(Math.abs(change.y - remove.y)).toBeLessThan(2);
    expect(remove.x).toBeGreaterThanOrEqual(change.x + change.width - 1);
    expect(name.x).toBeLessThan(change.x);
    expect(change.y).toBeLessThan(name.y + name.height);
    if (SHOTS)
      await group.screenshot({
        path: `${SHOTS}/mottagare__375__${locale}.png`,
      });

    await buttons.nth(0).click();
    const cancel = group.getByRole("button", {
      name: locale === "sv" ? "Avbryt sökning" : "Cancel search",
    });
    await expect(cancel).toBeVisible();
    // No "Stäng"/"Close" in the search: the form's own Cancel is the only other way out.
    await expect(
      group.getByRole("button", { name: locale === "sv" ? "Stäng" : "Close" }),
    ).toHaveCount(0);
    expect(await hasNoSidewaysScroll(page)).toBe(true);
    if (SHOTS)
      await group.screenshot({
        path: `${SHOTS}/mottagare-sok__375__${locale}.png`,
      });
    await cancel.click();
    await expect(group.locator(".shopping-recipient-name")).toBeVisible();
    expect(opened.failures).toEqual([]);
  });
}
