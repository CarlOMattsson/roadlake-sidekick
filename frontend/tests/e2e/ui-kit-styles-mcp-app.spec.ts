import { expect, test, type FrameLocator } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import {
  box,
  pseudoStyle,
  resolved,
  resolvedWithin,
  style,
} from "./computed-style";
import {
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import {
  bigAgenda,
  bigBoard,
  bigContactList,
  bigShoppingDetail,
  shoppingReplies,
  workReplies,
} from "./one-screen-fixtures";
import { journalDay } from "./sidekick-domain-fixtures";

// The shared kit of the rooms (the row, the fold and the action row, the two-column frame, the counts bar, the
// skeleton, the button floor) measured in a real Chromium from computed style and boxes, on the rooms that use it.
// Simulated host (see mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture.

/** The `font` shorthand of a design token, resolved in the page into size, weight and line height. */
async function typed(app: FrameLocator, token: string) {
  return app.locator("#root").evaluate((root, value) => {
    const probe = document.createElement("span");
    root.appendChild(probe);
    probe.style.font = value;
    const computed = getComputedStyle(probe);
    const out = {
      fontSize: computed.fontSize,
      fontWeight: computed.fontWeight,
      lineHeight: computed.lineHeight,
    };
    probe.remove();
    return out;
  }, `var(${token})`);
}

test("Row: a 48 px floor with no hairline, 6 px of air over and under the open area, a title cut at 3 lines and one meta line cut with an ellipsis", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "list_contacts",
    result: bigContactList,
    replies: workReplies,
  });
  await settled(app);
  const row = app.locator("li.sk-row").first();
  await expect(row).toBeVisible();
  expect((await box(row)).height).toBeGreaterThanOrEqual(48);
  expect((await style(row, "borderBottomWidth")).borderBottomWidth).toBe("0px");
  const air = await resolved(app, "padding-top", "var(--sk-row-pad)");
  expect(
    await style(
      row.locator(".sk-row-open"),
      "paddingTop",
      "paddingBottom",
      "paddingLeft",
    ),
  ).toEqual({ paddingTop: air, paddingBottom: air, paddingLeft: "0px" });
  // The title is cut only by the line-limit token: 3 in a full-screen list.
  expect(
    (await style(row.locator(".sk-row-primary"), "webkitLineClamp"))
      .webkitLineClamp,
  ).toBe("3");
  // The meta line is one line, cut with an ellipsis, and sits under the title.
  const secondary = app.locator(".sk-row-secondary").first();
  expect(
    await style(secondary, "whiteSpace", "textOverflow", "overflowX"),
  ).toEqual({
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
    overflowX: "hidden",
  });
  expect((await box(secondary)).height).toBeLessThan(
    2 *
      Number.parseFloat(
        (await style(secondary, "lineHeight")).lineHeight ?? "",
      ),
  );
  expect(failures).toEqual([]);
});

test("Action row: a list's tertiary row is 48 high in medium ink with no fill or edge, its glyph in the ring's column", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    replies: workReplies,
  });
  await settled(app);
  // The overdue block offers one action row: move them all.
  const action = app.locator("button.sk-action-row").first();
  await expect(action).toBeVisible();
  expect((await box(action)).height).toBeGreaterThanOrEqual(48);
  expect(
    await style(action, "color", "borderTopWidth", "backgroundColor"),
  ).toEqual({
    color: await resolved(app, "color", "var(--sk-fg)"),
    borderTopWidth: "0px",
    backgroundColor: "rgba(0, 0, 0, 0)",
  });
  expect((await style(action, "fontWeight")).fontWeight).toBe(
    await resolved(app, "font-weight", "var(--sk-weight-medium)"),
  );
  const glyph = await box(action.locator("svg"));
  expect(glyph.width).toBeCloseTo(
    Number.parseFloat(await resolved(app, "width", "var(--sk-ring-glyph)")),
    0,
  );
  expect(failures).toEqual([]);
});

test("Fold: the section type in ink on a 48 px target with no fill or edge, its meta line in the meta type, and its ⌄ turns up when open and not before", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "get_journal_day",
    result: {
      ...journalDay,
      done: {
        tasks: [],
        steps: [],
        purchases: [],
        counts: { tasks: 2, steps: 0, purchases: 0 },
        truncated: false,
      },
    },
  });
  await settled(app);
  const fold = app.locator("button.sk-fold").first();
  await expect(fold).toBeVisible();
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  expect((await box(fold)).height).toBeGreaterThanOrEqual(48);
  expect(
    await style(fold, "color", "borderTopWidth", "backgroundColor"),
  ).toEqual({
    color: await resolved(app, "color", "var(--sk-fg)"),
    borderTopWidth: "0px",
    backgroundColor: "rgba(0, 0, 0, 0)",
  });
  const section = await typed(app, "--sk-type-section");
  const foldType = await style(
    fold.locator(".sk-fold-text"),
    "fontSize",
    "fontWeight",
  );
  expect(foldType).toEqual({
    fontSize: section.fontSize,
    fontWeight: section.fontWeight,
  });
  const meta = fold.locator(".sk-fold-meta");
  await expect(meta).toBeVisible();
  expect((await style(meta, "fontSize")).fontSize).toBe(
    (await typed(app, "--sk-type-meta")).fontSize,
  );
  expect((await style(meta, "color")).color).toBe(
    await resolved(app, "color", "var(--sk-muted)"),
  );
  const chevron = fold.locator("svg");
  expect((await style(chevron, "transform")).transform).toBe("none");
  await fold.click();
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  // Turned half a revolution (the matrix of rotate(180deg)), once its transition has run.
  await expect
    .poll(async () => (await style(chevron, "transform")).transform)
    .toBe("matrix(-1, 0, 0, -1, 0, 0)");
  expect(failures).toEqual([]);
});

test("Fold: a closed fold's ⌄ does not turn, and the shopping list's fold is a 48 px target too", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "get_shopping_list",
    result: bigShoppingDetail,
    replies: shoppingReplies,
  });
  await settled(app);
  const fold = app.locator("button.sk-fold").first();
  await expect(fold).toBeVisible();
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  expect((await style(fold.locator("svg"), "transform")).transform).toBe(
    "none",
  );
  expect((await box(fold)).height).toBeGreaterThanOrEqual(48);
  expect(failures).toEqual([]);
});

test("Counts bar: the legend wraps instead of scrolling at 320 px, and each swatch is drawn as its segment", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 320,
    theme: "light",
    tool: "get_work_board",
    result: bigBoard,
    displayMode: "inline",
    availableDisplayModes: ["inline"],
    replies: workReplies,
  });
  await settled(app);
  const legend = app.locator(".sk-counts-bar__legend");
  await expect(legend).toBeVisible();
  expect((await style(legend, "flexWrap")).flexWrap).toBe("wrap");
  expect(
    await legend.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  const track = app.locator(".sk-counts-bar__bar");
  const trackBox = await box(track);
  expect(trackBox.height).toBe(8);
  expect((await style(track, "borderTopLeftRadius")).borderTopLeftRadius).toBe(
    "2px",
  );
  const item = app.locator(".sk-counts-bar__item").first();
  const swatch = await pseudoStyle(
    item,
    "::before",
    "width",
    "height",
    "borderTopLeftRadius",
  );
  expect(swatch).toEqual({
    width: "12px",
    height: "8px",
    borderTopLeftRadius: "2px",
  });
  // Blockerad is a hatch inside a 1 px ink edge, not a colour: it never reads as the overdue red.
  const blocked = app.locator('.sk-counts-bar__item[data-tone="warning"]');
  const hatch = await pseudoStyle(
    blocked,
    "::before",
    "backgroundImage",
    "boxShadow",
  );
  expect(hatch.backgroundImage).toContain("repeating-linear-gradient");
  expect(hatch.boxShadow).toBe(
    await resolved(app, "box-shadow", "inset 0 0 0 1px var(--sk-fg)"),
  );
  expect(failures).toEqual([]);
});

test("Waiting placeholder: the skeleton blocks pulse, and stop under reduced motion", async ({
  page,
}) => {
  const waitingBlock = async (reduce: boolean) => {
    await page.emulateMedia({
      colorScheme: "light",
      reducedMotion: reduce ? "reduce" : "no-preference",
    });
    const { app, failures } = await openSimulatedApp(page, {
      resource: readBuiltApp("sidekick", "sv"),
      width: 390,
      height: 780,
      hostContext: {
        locale: "sv",
        theme: "light",
        displayMode: "fullscreen",
        availableDisplayModes: ["inline", "fullscreen"],
        toolInfo: { id: 1, tool: { name: "get_work_agenda" } },
      },
      replies: {},
    });
    await waitForAppInitialized(page);
    const block = app.locator(".sidekick-wait-block").first();
    await expect(block).toBeVisible();
    const animation = (await style(block, "animationName")).animationName;
    expect(failures).toEqual([]);
    return animation;
  };
  expect(await waitingBlock(false)).not.toBe("none");
  expect(await waitingBlock(true)).toBe("none");
});

test("Buttons: a button is at least the tap token high, and a fullscreen frame lifts every sticky notice above the foot reserve", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    replies: workReplies,
  });
  await settled(app);
  const tap = Number.parseFloat(await resolved(app, "width", "var(--sk-tap)"));
  expect(tap).toBeGreaterThanOrEqual(44);
  for (const button of await app.locator("button.sk-btn").all())
    if (await button.isVisible())
      expect((await box(button)).height).toBeGreaterThanOrEqual(tap);
  const frame = app.locator('.sk-frame[data-mode="full"]');
  expect(
    await resolvedWithin(frame, "padding-top", "var(--sk-notice-bottom)"),
  ).toBe(await resolvedWithin(frame, "padding-top", "var(--sk-foot-reserve)"));
  expect(failures).toEqual([]);
});
