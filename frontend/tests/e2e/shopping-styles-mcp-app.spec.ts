import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  box,
  pseudoStyle,
  resolved,
  resolvedWithin,
  style,
} from "./computed-style";
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
  } = {},
) {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("shopping", "en"),
    width: 375,
    height: 800,
    hostContext: {
      locale: "en",
      theme: "light",
      displayMode: mode === "fullscreen" ? "fullscreen" : "inline",
      // A host that cannot open fullscreen gets the compact list card; one that can gets the summary card.
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
  // Nothing in the list is sticky, so no Undo owns a strip of the screen.
  expect(
    await root.evaluate(
      (section) =>
        [...section.querySelectorAll("*")].filter(
          (element) => getComputedStyle(element).position === "sticky",
        ).length,
    ),
  ).toBe(0);

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
  expect(await style(ring, "alignItems")).toEqual({ alignItems: "flex-start" });
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
  // The progress is one line: the meta text, then a 6 px bar that takes the rest, 12 after it.
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
    minWidth: "0px",
    height: "6px",
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

test("a bought row holds its Undo as a compact secondary button with a 48 px target", async ({
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
  const undo = app.getByRole("button", { name: /^Undo bought / });
  await expect(undo).toBeVisible();
  expect(await style(undo, "minHeight", "borderTopWidth")).toEqual({
    minHeight: await resolved(app, "min-height", "var(--sk-compact)"),
    borderTopWidth: await resolved(app, "padding-top", "var(--sk-hairline)"),
  });
  const target = await effectiveTargetSize(undo);
  expect(target?.height).toBeCloseTo(48, 0);
  // The meta text names what happened, and the rows have no hairline between them.
  const held = app.locator(".shopping-held-item").first();
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
  // A store heading is one line of small text, cut with an ellipsis.
  const heading = card.locator(".shopping-group > h3").first();
  expect(
    await style(heading, "whiteSpace", "textOverflow", "fontSize"),
  ).toEqual({
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
    fontSize: await resolved(app, "font-size", "0.8rem"),
  });
  // An open row is a 44 px tap target with no padding of its own; its text column takes the width and may shrink.
  const openRow = card.locator(".shopping-items--folded > li").first();
  const check = openRow.locator(".shopping-check");
  expect(await style(openRow, "paddingTop", "paddingBottom")).toEqual({
    paddingTop: "0px",
    paddingBottom: "0px",
  });
  expect(await style(check, "position", "minHeight")).toEqual({
    position: "relative",
    minHeight: await resolved(app, "min-height", "2.75rem"),
  });
  expect((await box(check)).height).toBeGreaterThanOrEqual(44);
  const text = check.locator(".shopping-item-text");
  expect(await style(text, "flexGrow", "minWidth", "overflowWrap")).toEqual({
    flexGrow: "1",
    minWidth: "0px",
    overflowWrap: "anywhere",
  });
  // The status is a muted meta line.
  const status = check.locator(".shopping-status").first();
  expect(await style(status, "color", "fontSize")).toEqual({
    color: await resolvedWithin(card, "color", "var(--work-muted)"),
    fontSize: await resolved(app, "font-size", "0.9rem"),
  });
  // The native checkbox is invisible and covers the whole row, so the row is its hit area.
  const checkbox = check.locator('input[type="checkbox"]');
  expect(await style(checkbox, "position", "opacity")).toEqual({
    position: "absolute",
    opacity: "0",
  });
  const [rowBox, checkboxBox] = await Promise.all([box(check), box(checkbox)]);
  expect(checkboxBox.x).toBeCloseTo(rowBox.x, 0);
  expect(checkboxBox.y).toBeCloseTo(rowBox.y, 0);
  expect(checkboxBox.width).toBeCloseTo(rowBox.width, 0);
  expect(checkboxBox.height).toBeCloseTo(rowBox.height, 0);
  // The status glyph is the visible ring, 24 px in the leading column.
  const glyph = check.locator(".sk-status-glyph");
  expect(await style(glyph, "width", "height")).toEqual({
    width: await resolved(app, "width", "var(--sk-icon)"),
    height: await resolved(app, "height", "var(--sk-icon)"),
  });
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

  // Show all opens the list in place: its rows have no hairline and the add row is 48 high.
  await card.getByRole("button", { name: /^Show all/ }).click();
  const opened = app.locator("section.sidekick-shopping");
  const listRow = opened.locator(".shopping-items > li").first();
  expect(
    await style(listRow, "paddingTop", "borderTopWidth", "borderBottomWidth"),
  ).toEqual({
    paddingTop: await resolved(app, "padding-top", "var(--sk-row-pad)"),
    borderTopWidth: "0px",
    borderBottomWidth: "0px",
  });
  // A toolbar field takes its own row basis: the list picker is not squeezed beside the buttons.
  const field12 = opened
    .locator(".shopping-toolbar > label:not(.shopping-check)")
    .first();
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
  const { app, failures } = await openShopping(page, "card");
  const body = app.locator(".shopping-card-body");
  const title = app.locator(".sk-card__title");
  const items = app.locator(".shopping-card-item");
  // Its height is its content's: the card ends where its last child and its own padding end, nothing is reserved below.
  const slack = await body.evaluate((card) => {
    const last = card.lastElementChild!.getBoundingClientRect();
    const own = getComputedStyle(card);
    return (
      card.getBoundingClientRect().bottom -
      (last.bottom +
        Number.parseFloat(own.paddingBottom) +
        Number.parseFloat(own.borderBottomWidth))
    );
  });
  expect(Math.abs(slack)).toBeLessThan(1);
  for (const target of [title, items.first()] as Locator[]) {
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

test("the failure notice puts its actions on their own row under the message", async ({
  page,
}) => {
  // The lists read fine, the list that opens does not: the card-level notice shows with its actions.
  const { app, failures } = await openShopping(page, "compact", {
    tool: "list_shopping_lists",
    result: { lists: [sList], next_offset: null },
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
    },
  });
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
