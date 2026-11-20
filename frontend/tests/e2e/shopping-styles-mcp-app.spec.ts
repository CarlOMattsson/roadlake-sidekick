import {
  expect,
  test,
  type FrameLocator,
  type Locator,
  type Page,
} from "@playwright/test";
import { box, pseudoStyle, resolved, style } from "./computed-style";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import { sItem, sList } from "./one-screen-fixtures";

// The look of the Shopping room measured in a real Chromium: computed style and boxes of the rendered rows, the store
// view, the compact card and the failure notice. Simulated host (see mcp-host-fixture.ts), not a real Claude or
// Android host: every tool answer is a fixture. Where a value is a design token, the expected value is the token
// resolved in the page.

const milk = sItem(1, "Mjölk", { quantity: "2", unit: "l", store: "ICA" });
const bread = sItem(2, "Bröd", { store: "ICA" });
const eggs = sItem(3, "Ägg", {
  store: "ICA",
  purchased: true,
  purchased_at: "2026-11-13T10:00:00Z",
});
const detail = {
  shopping_list: sList,
  items: [milk, bread, sItem(4, "Kaffe"), eggs],
  next_offset: null,
  evaluated_on: "2026-11-13",
};
/** Enough open rows that the compact card folds some of them behind "Show all". */
const longDetail = {
  ...detail,
  items: Array.from({ length: 12 }, (_, index) =>
    sItem(index + 1, `Vara ${index + 1}`, {
      store: index % 2 === 0 ? "ICA" : null,
    }),
  ),
};
const listReplies = {
  list_shopping_lists: {
    structuredContent: { lists: [sList], next_offset: null },
  },
  get_shopping_list: { structuredContent: detail },
};

type Mode = "fullscreen" | "compact" | "card";

async function openShopping(
  page: Page,
  mode: Mode,
  options: {
    result?: unknown;
    replies?: Record<string, unknown>;
    safeBottom?: number;
    tool?: string;
    width?: number;
  } = {},
) {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("shopping", "en"),
    width: options.width ?? 375,
    height: 800,
    hostContext: {
      locale: "en",
      theme: "light",
      displayMode: mode === "fullscreen" ? "fullscreen" : "inline",
      // Inline the list is the folded view either way; a host that can open fullscreen also gets its open link.
      availableDisplayModes:
        mode === "card"
          ? ["inline", "fullscreen"]
          : mode === "compact"
            ? ["inline"]
            : ["inline", "fullscreen"],
      ...(options.tool === undefined
        ? {}
        : { toolInfo: { id: 1, tool: { name: options.tool } } }),
      ...(options.safeBottom === undefined
        ? {}
        : {
            safeAreaInsets: {
              top: 0,
              right: 0,
              bottom: options.safeBottom,
              left: 0,
            },
          }),
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: options.replies ?? listReplies,
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, options.result ?? detail);
  await settled(opened.app);
  return opened;
}

const px = (value: string | undefined) => Number.parseFloat(value ?? "");

test("the store view keeps its rows, amounts, progress and reserve in the right measure", async ({
  page,
}) => {
  const { app, failures } = await openShopping(page, "fullscreen", {
    safeBottom: 24,
  });
  const root = app.locator("section.sidekick-shopping");
  // Fullscreen keeps the foot reserve (6rem, or the safe area when that is larger) clear for the host's reply field,
  // and the safe area is not added again. The text falls back to 16 px.
  const frameBody = app.locator(
    ".sk-frame[data-mode='full'] > .sk-frame__body",
  );
  const reserve = (await style(frameBody, "paddingBottom")).paddingBottom;
  expect(reserve).toBe(
    await resolved(
      app,
      "padding-bottom",
      "calc(16px + max(var(--host-safe-bottom, 0px), 6rem))",
    ),
  );
  expect(px(reserve)).toBe(16 + 96);
  expect(await style(root, "fontSize")).toEqual({
    fontSize: await resolved(
      app,
      "font-size",
      "var(--font-text-md-size, 16px)",
    ),
  });
  // Nothing in the list is sticky: the receipt bar is the one sticky thing, and it has no box while empty, so no row
  // or Undo of its own owns a strip of the screen.
  expect(
    await root.evaluate((section) =>
      [...section.querySelectorAll("*")]
        .filter((element) => getComputedStyle(element).position === "sticky")
        .map((element) => element.className),
    ),
  ).toEqual(["sk-receipt-slot"]);

  // A store row is a 48 px tap target; its list item has no padding of its own and no hairline.
  const row = app.locator(".shopping-store-row").first();
  expect(await style(row, "minHeight")).toEqual({ minHeight: "48px" });
  expect((await box(row)).height).toBeGreaterThanOrEqual(48);
  const item = app.locator("li.shopping-store-item").first();
  expect(
    await style(item, "paddingTop", "paddingBottom", "borderTopWidth"),
  ).toEqual({ paddingTop: "0px", paddingBottom: "0px", borderTopWidth: "0px" });
  // The ring is a stretched button as wide as the row template's leading column, its glyph on the first title line,
  // and its ::after reaches 2 px past each side.
  const line = app.locator(".shopping-store-line").first();
  const ring = app.locator("button.shopping-ring").first();
  expect(await style(line, "alignItems")).toEqual({ alignItems: "stretch" });
  expect(await style(ring, "alignItems")).toEqual({
    alignItems: await resolved(app, "align-items", "flex-start"),
  });
  expect(await style(ring, "width")).toEqual({
    width: await resolved(app, "width", "var(--sk-lead-w)"),
  });
  const after = await pseudoStyle(
    ring,
    "::after",
    "top",
    "right",
    "bottom",
    "left",
  );
  expect(after).toEqual({
    top: "0px",
    right: "-2px",
    bottom: "0px",
    left: "-2px",
  });
  // The amount ends on the content edge: tabular figures, no margin, no fixed width, no alignment of its own.
  const qty = app.locator(".shopping-store-qty").first();
  expect(
    await style(qty, "fontVariantNumeric", "marginRight", "minWidth"),
  ).toEqual({
    fontVariantNumeric: "tabular-nums",
    marginRight: "0px",
    minWidth: "auto",
  });
  expect(await style(qty, "textAlign")).toEqual(
    await style(qty.locator(".."), "textAlign"),
  );
  // The progress is one line: the meta text, then the shared 4 px bar that takes the rest, 12 after it.
  const progress = app.locator(".shopping-progress > .sk-progress");
  expect(
    await style(progress, "display", "alignItems", "gap", "flexDirection"),
  ).toEqual({
    display: "flex",
    alignItems: "center",
    gap: await resolved(app, "gap", "var(--sk-s3)"),
    flexDirection: "row",
  });
  const track = progress.locator(".sk-progress__track");
  expect(
    await style(
      track,
      "flexGrow",
      "flexShrink",
      "flexBasis",
      "minWidth",
      "height",
    ),
  ).toEqual({
    flexGrow: "1",
    flexShrink: "1",
    flexBasis: "auto",
    minWidth: await resolved(app, "min-width", "3rem"),
    height: "4px",
  });
  // The fill is the text colour, the one colour every progress bar has.
  expect(
    await style(progress.locator(".sk-progress__fill"), "backgroundColor"),
  ).toEqual({
    backgroundColor: await resolved(app, "background-color", "var(--sk-fg)"),
  });
  const [text, bar] = await Promise.all([
    box(progress.locator(".sk-progress__text")),
    box(track),
  ]);
  expect(
    Math.abs(bar.y + bar.height / 2 - (text.y + text.height / 2)),
  ).toBeLessThan(2);
  // The Purchased fold turns its icon up while it is open.
  const fold = app.locator(".shopping-purchased > button.sk-fold");
  const closed = await style(fold.locator("svg"), "transform");
  await fold.click();
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  expect(await style(fold.locator("svg"), "transform")).toEqual({
    transform: await resolved(app, "transform", "rotate(180deg)"),
  });
  expect(closed.transform).not.toBe(
    await resolved(app, "transform", "rotate(180deg)"),
  );
  // The loading line is a badge taken out of the flow: a line added to the card does not move the rows.
  const before = await box(row);
  await root.evaluate((section) => {
    const loading = document.createElement("p");
    loading.className = "shopping-loading";
    loading.textContent = "Loading";
    section.prepend(loading);
  });
  const loading = app.locator(".sidekick-shopping > .shopping-loading");
  expect(await style(loading, "position")).toEqual({ position: "absolute" });
  expect(await box(row)).toEqual(before);
  expect(failures).toEqual([]);
});

test("a bought row's Undo is the receipt bar's compact tertiary button with a 48 px target, and the row keeps its look", async ({
  page,
}) => {
  const { app, failures } = await openShopping(page, "fullscreen", {
    replies: {
      ...listReplies,
      set_shopping_item_purchased: {
        structuredContent: {
          item: { ...milk, purchased: true, version: 2 },
          evaluated_on: "2026-11-13",
        },
      },
    },
  });
  await app.getByRole("button", { name: "Mark Mjölk as bought" }).click();
  const undo = app
    .locator(".sk-receipt-slot")
    .getByRole("button", { name: "Undo" });
  await expect(undo).toBeVisible();
  await expect(undo).toHaveClass(/sk-btn--quiet/);
  expect(await style(undo, "minHeight", "borderTopWidth")).toEqual({
    minHeight: await resolved(app, "min-height", "var(--sk-compact)"),
    borderTopWidth: await resolved(app, "padding-top", "var(--sk-hairline)"),
  });
  const target = await effectiveTargetSize(undo);
  expect(target?.height).toBeCloseTo(48, 0);
  // The row has no Undo of its own and no hairline, and the rows have none between them.
  const held = app.locator(".shopping-held-item").first();
  await expect(held.getByRole("button", { name: /^Undo/ })).toHaveCount(0);
  expect(await style(held, "borderBottomWidth")).toEqual({
    borderBottomWidth: "0px",
  });
  expect(failures).toEqual([]);
});

test("the compact card keeps its rows, headings and add field in a phone's measure", async ({
  page,
}) => {
  const { app, failures } = await openShopping(page, "compact", {
    result: longDetail,
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
      get_shopping_list: { structuredContent: longDetail },
    },
  });
  const card = app.locator("section.sidekick-shopping.shopping-folded");
  await expect(card).toBeVisible();
  // A store heading is one line, cut with an ellipsis, in the section type every mode uses (2026-11-20: the 12.8 px
  // heading was too small to read in a shop).
  const heading = card.locator(".shopping-group > h3").first();
  expect(
    await style(heading, "whiteSpace", "textOverflow", "fontSize"),
  ).toEqual({
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
    fontSize: await resolved(app, "font-size", "var(--sk-type-section-size)"),
  });
  // An open row is the store view's row (2026-11-20: one row in every mode): no padding of its own, the ring and the
  // row button both at least 44 px high, and the name column takes the width and may shrink.
  const openRow = card.locator(".shopping-items--folded > li").first();
  expect(await style(openRow, "paddingTop", "paddingBottom")).toEqual({
    paddingTop: "0px",
    paddingBottom: "0px",
  });
  const ring = openRow.locator(".shopping-ring");
  const rowButton = openRow.locator(".shopping-store-row");
  expect((await box(ring)).height).toBeGreaterThanOrEqual(44);
  expect((await box(ring)).width).toBeGreaterThanOrEqual(44);
  expect((await box(rowButton)).height).toBeGreaterThanOrEqual(44);
  expect(
    await style(
      openRow.locator(".shopping-store-body"),
      "flexGrow",
      "minWidth",
    ),
  ).toEqual({ flexGrow: "1", minWidth: "0px" });
  // The folded card is one phone screen: a long name takes two lines at most, and the row has no - + (they wait in
  // "Show all" and the full list); the row menu stays.
  const name = openRow.locator(".shopping-store-name");
  expect(
    await name.evaluate((element) =>
      getComputedStyle(element).getPropertyValue("-webkit-line-clamp"),
    ),
  ).toBe("2");
  await expect(openRow.locator(".shopping-step")).toHaveCount(0);
  // An open row has no status line: its ring says it is still to buy. The status only shows while an Undo holds.
  await expect(openRow.locator(".shopping-held")).toHaveCount(0);
  // The ring is the 24 px status glyph.
  const glyph = ring.locator(".sk-status-glyph");
  expect((await box(glyph)).width).toBeCloseTo(24, 0);
  // The add field and its button share one row, both 44 px high.
  const [field, add] = await Promise.all([
    box(card.locator(".shopping-batch > input")),
    box(card.locator(".shopping-batch > button")),
  ]);
  expect(field.height).toBeGreaterThanOrEqual(44);
  expect(add.height).toBeGreaterThanOrEqual(44);
  expect(
    Math.abs(field.y + field.height / 2 - (add.y + add.height / 2)),
  ).toBeLessThan(2);
  expect(add.x).toBeGreaterThanOrEqual(field.x + field.width - 1);

  // Show all only lifts the row cap: the card stays compact (no hairline) and lists every open row.
  const shown = await card.locator(".shopping-items--folded > li").count();
  await card.getByRole("button", { name: /^Show all/ }).click();
  await expect(card.locator(".shopping-items--folded > li")).toHaveCount(12);
  expect(shown).toBeLessThan(12);
  expect(
    await style(
      card.locator(".shopping-items--folded > li").first(),
      "paddingTop",
      "borderTopWidth",
      "borderBottomWidth",
    ),
  ).toEqual({
    paddingTop: "0px",
    borderTopWidth: "0px",
    borderBottomWidth: "0px",
  });
  // The list's own forms wait behind the card's ⋯ menu. A labelled field in a toolbar takes its own row basis,
  // so the list-name field of "Edit list" is not squeezed beside its button.
  await app.getByRole("button", { name: "More options", exact: true }).click();
  await app.getByRole("button", { name: "Edit list" }).click();
  const field12 = app
    .locator(".shopping-rename.shopping-toolbar > label")
    .first();
  await expect(field12).toBeVisible();
  expect(await style(field12, "flexBasis", "flexGrow", "flexShrink")).toEqual({
    flexBasis: await resolved(app, "flex-basis", "12rem"),
    flexGrow: "1",
    flexShrink: "1",
  });
  expect(failures).toEqual([]);
});

test("the shop view in the conversation keeps its + Add item row 48 high", async ({
  page,
}) => {
  const shopDetail = { ...detail, store: "ICA" };
  const { app, failures } = await openShopping(page, "card", {
    result: shopDetail,
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
      get_shopping_list: { structuredContent: shopDetail },
    },
  });
  const addRow = app.locator(".shopping-add-row");
  await expect(addRow).toBeVisible();
  expect(await style(addRow, "minHeight")).toEqual({
    minHeight: await resolved(app, "min-height", "var(--sk-tap-lg)"),
  });
  expect((await box(addRow)).height).toBeGreaterThanOrEqual(48);
  expect(failures).toEqual([]);
});

test("the inline card grows with its content, and its title and rows wrap to two lines before they are clipped", async ({
  page,
}) => {
  // With fullscreen on offer the inline list is the folded view (2026-11-20: one row in every mode), the card itself.
  const { app, failures } = await openShopping(page, "card");
  const card = app.locator("section.sidekick-shopping.shopping-folded");
  await expect(card).toBeVisible();
  const title = card.locator(".sk-back-header__title");
  const name = card.locator(".shopping-store-name").first();
  // Its height is its content's: the card ends where its last child and its own padding end, nothing is reserved below.
  const slack = await card.evaluate((element) => {
    const last = element.lastElementChild!.getBoundingClientRect();
    const own = getComputedStyle(element);
    return (
      element.getBoundingClientRect().bottom -
      (last.bottom +
        Number.parseFloat(own.paddingBottom) +
        Number.parseFloat(own.borderBottomWidth))
    );
  });
  expect(Math.abs(slack)).toBeLessThan(1);
  for (const target of [title, name] as Locator[]) {
    const clamp = await target.evaluate((element) => {
      const computed = getComputedStyle(element);
      return {
        lines: computed.getPropertyValue("-webkit-line-clamp"),
        orient: computed.getPropertyValue("-webkit-box-orient"),
        wrap: computed.whiteSpace,
      };
    });
    expect(clamp.lines).toBe("2");
    expect(clamp.orient).toBe("vertical");
    expect(clamp.wrap).not.toBe("nowrap");
  }
  expect(failures).toEqual([]);
});

test("the batch card does not clip the names it lists", async ({ page }) => {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("shopping", "en"),
    width: 375,
    height: 700,
    hostContext: {
      locale: "en",
      theme: "light",
      displayMode: "inline",
      availableDisplayModes: ["inline", "fullscreen"],
    },
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, {
    items: [{ item: sItem(1, "Mjölk") }, { item: sItem(2, "Ägg") }],
  });
  await settled(opened.app);
  const names = opened.app.locator(".shopping-batch-names");
  await expect(names).toBeVisible();
  expect(
    await names.evaluate((element) =>
      getComputedStyle(element).getPropertyValue("-webkit-line-clamp"),
    ),
  ).toBe("none");
  expect(opened.failures).toEqual([]);
});

test("a failed read is the view's error box: its one action fits, is a 48 px target and nothing is clipped", async ({
  page,
}) => {
  // The lists read fine, the list that opens does not: the view's MessageBox shows, with "Try again" as its one action.
  const { app, failures } = await openShopping(page, "compact", {
    tool: "list_shopping_lists",
    result: { lists: [sList], next_offset: null },
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
    },
  });
  const alert = app.getByRole("alert");
  await expect(alert).toHaveClass(/sk-message--error/);
  const retry = alert.getByRole("button", { name: "Try again" });
  await expect(retry).toBeVisible();
  await expect(alert.getByRole("button")).toHaveCount(1);
  const [alertBox, retryBox, target] = await Promise.all([
    box(alert),
    box(retry),
    effectiveTargetSize(retry),
  ]);
  // The action stands inside the box, and its target is 44 px high at least.
  expect(retryBox.x).toBeGreaterThanOrEqual(alertBox.x);
  expect(retryBox.x + retryBox.width).toBeLessThanOrEqual(
    alertBox.x + alertBox.width + 0.5,
  );
  expect(retryBox.y + retryBox.height).toBeLessThanOrEqual(
    alertBox.y + alertBox.height + 0.5,
  );
  expect(target?.height ?? retryBox.height).toBeGreaterThanOrEqual(44);
  // No text is cut off: neither the box nor its title and text scroll or clip their content.
  expect(
    await alert.evaluate((element) =>
      [element, ...element.querySelectorAll("p")].every(
        (node) =>
          node.scrollWidth <= node.clientWidth + 0.5 &&
          node.scrollHeight <= node.clientHeight + 0.5,
      ),
    ),
  ).toBe(true);
  expect(
    await app
      .locator("html")
      .evaluate((root) => root.scrollWidth <= root.clientWidth),
  ).toBe(true);
  expect(failures).toEqual([]);
});

test("the failure notice under a row puts its actions on their own row under the message", async ({
  page,
}) => {
  // A refused quantity step is not the bought mark: the row's notice shows the full message, with its two actions
  // wrapped on their own row under it.
  const { app, failures } = await openShopping(page, "fullscreen");
  await app.getByRole("button", { name: "Increase quantity of Mjölk" }).click();
  const actions = app.locator(".shopping-failure-actions");
  await expect(actions).toBeVisible();
  expect(await style(actions, "flexWrap")).toEqual({ flexWrap: "wrap" });
  const [message, buttons] = await Promise.all([
    box(app.locator(".shopping-failure > p")),
    box(actions),
  ]);
  expect(buttons.y).toBeGreaterThanOrEqual(message.y + message.height - 1);
  expect(failures).toEqual([]);
});

// A tick is in place: it moves nothing under the thumb, and the receipt bar floats over the foot of the window without
// covering the list's header. Simulated host, 390 px wide, fullscreen: not a real Claude or Android run.
const twoLineName = "Krossade tomater ekologiska";
const tickItems = [
  sItem(1, twoLineName, { store: "ICA" }),
  sItem(2, "Mjölk", { quantity: "2", unit: "l", store: "ICA" }),
  ...Array.from({ length: 14 }, (_, index) =>
    sItem(10 + index, `Vara ${index + 1}`, {
      store: index % 2 === 0 ? "Coop" : "Hemköp",
    }),
  ),
];

/** The store view at 390 px; `ticked` is the item whose purchase the host accepts. */
function openTicking(page: Page, ticked: (typeof tickItems)[number]) {
  const tickDetail = { ...detail, items: tickItems };
  return openShopping(page, "fullscreen", {
    width: 390,
    result: tickDetail,
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
      get_shopping_list: { structuredContent: tickDetail },
      set_shopping_item_purchased: {
        structuredContent: {
          item: { ...ticked, purchased: true, version: 2 },
          evaluated_on: "2026-11-13",
        },
      },
    },
  });
}

/** Ticks `name`, lets the page settle and scrolls back to the top (the tap scrolled the ring into view). */
async function tick(app: FrameLocator, name: string) {
  await app.getByRole("button", { name: `Mark ${name} as bought` }).click();
  await expect(app.locator(".sk-receipt-slot .sk-receipt")).toBeVisible();
  await settled(app);
  await app.locator("html").evaluate(() => window.scrollTo(0, 0));
}

const storeHeadingTops = (app: FrameLocator) =>
  app
    .locator(".shopping-group > h3")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().top),
    );

test("a tick moves no store heading, and the bar rests in the window below the list's header", async ({
  page,
}) => {
  const { app, failures } = await openTicking(page, tickItems[2]!);
  const before = await storeHeadingTops(app);
  expect(before.length).toBeGreaterThanOrEqual(3);
  await tick(app, "Vara 1");
  // The held row stays in its place, so the headings under it have not moved.
  await expect(app.locator(".shopping-held-item")).toHaveCount(1);
  expect(await storeHeadingTops(app)).toEqual(before);
  // The bar lies inside the window (fullscreen is 800 high) and does not cover the header with the list's name.
  const [barBox, headBox] = await Promise.all([
    box(app.locator(".sk-receipt-slot .sk-receipt")),
    box(app.locator(".shopping-head")),
  ]);
  expect(barBox.x).toBeGreaterThanOrEqual(0);
  expect(barBox.x + barBox.width).toBeLessThanOrEqual(390 + 0.5);
  expect(barBox.y).toBeGreaterThanOrEqual(headBox.y + headBox.height);
  expect(barBox.y + barBox.height).toBeLessThanOrEqual(800 + 0.5);
  expect(failures).toEqual([]);
});

// A held row says "Bought" in the room its quick changes had, so its name keeps its width and wraps as before.
test("a two-line row keeps its height when it is ticked", async ({ page }) => {
  const { app, failures } = await openTicking(page, tickItems[0]!);
  const row = app
    .locator("li.shopping-store-item")
    .filter({ hasText: twoLineName });
  const before = await box(row);
  expect(before.height).toBeGreaterThan(48);
  await tick(app, twoLineName);
  const after = await box(
    app.locator(".shopping-held-item").filter({ hasText: twoLineName }),
  );
  expect(after.y).toBeCloseTo(before.y, 0);
  expect(after.height).toBeCloseTo(before.height, 0);
  expect(failures).toEqual([]);
});
