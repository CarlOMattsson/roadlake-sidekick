import { expect, test, type Page } from "@playwright/test";
import { box, resolved, resolvedWithin, style } from "./computed-style";
import {
  openSimulatedApp,
  readBuiltApp,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// The placeholder shown while the host has not yet sent a result (awaiting.css), measured in a real Chromium from
// computed style and boxes, instead of read out of the stylesheet. Simulated host (see mcp-host-fixture.ts), not a real
// Claude or Android host. No tool result is ever delivered here, so the app stays on the placeholder.

async function openWaiting(
  page: Page,
  options: { safeAreaInsets?: Record<string, number> } = {},
) {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    width: 375,
    height: 800,
    hostContext: {
      locale: "en",
      theme: "light",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: "get_work_agenda" } },
      ...options,
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: {},
  });
  await waitForAppInitialized(page);
  await expect(opened.app.locator(".sidekick-wait-strip")).toBeVisible();
  return opened;
}

test("the placeholder pads 16 at the sides and 8 above plus the host's safe area, has no corner radius of its own, and draws the strip 40 high", async ({
  page,
}) => {
  const { app, failures } = await openWaiting(page, {
    safeAreaInsets: { top: 10, right: 6, bottom: 20, left: 4 },
  });
  const container = app.locator(".sidekick-wait");
  await expect(container).toBeVisible();
  expect(
    await style(
      container,
      "paddingTop",
      "paddingRight",
      "paddingBottom",
      "paddingLeft",
      "borderTopLeftRadius",
    ),
  ).toEqual({
    paddingTop: "18px",
    paddingRight: "22px",
    paddingBottom: "36px",
    paddingLeft: "20px",
    borderTopLeftRadius: "0px",
  });
  // The strip: 40 px high, a row of cells sharing it equally, none narrower than its label.
  const strip = app.locator(".sidekick-wait-strip");
  expect(await style(strip, "display", "height")).toEqual({
    display: "flex",
    height: "40px",
  });
  const rooms = await app.locator(".sidekick-wait-room").all();
  expect(rooms).toHaveLength(4);
  for (const room of rooms)
    expect(await style(room, "flexGrow", "flexShrink", "minWidth")).toEqual({
      flexGrow: "1",
      flexShrink: "1",
      minWidth: "min-content",
    });
  const widths = await Promise.all(
    rooms.map(async (room) => (await box(room)).width),
  );
  for (const width of widths)
    expect(Math.abs(width - widths[0]!)).toBeLessThan(6);
  expect(failures).toEqual([]);
});

test("the placeholder's rows have the row template's 48 floor and 6 of padding, a ring drawn as a contour, and a shorter second bar", async ({
  page,
}) => {
  const { app, failures } = await openWaiting(page);
  const row = app.locator(".sidekick-wait-row").first();
  await expect(row).toBeVisible();
  expect(
    await style(
      row,
      "minHeight",
      "paddingTop",
      "paddingBottom",
      "gridTemplateColumns",
    ),
  ).toMatchObject({
    minHeight: await resolved(app, "min-height", "var(--sk-row-min, 48px)"),
    paddingTop: await resolved(app, "padding-top", "var(--sk-row-pad, 6px)"),
    paddingBottom: await resolved(
      app,
      "padding-bottom",
      "var(--sk-row-pad, 6px)",
    ),
  });
  // A 40 px leading column, so the title starts at x 56 with the 16 px padding.
  const [rowBox, titleBox] = await Promise.all([
    box(row),
    box(row.locator(".sidekick-wait-row-title").first()),
  ]);
  expect(titleBox.x - rowBox.x).toBeCloseTo(40, 0);
  // The glyph is the ring's box, and a contour, not a filled disc.
  const glyph = row.locator(".sidekick-wait-glyph");
  expect(
    await style(
      glyph,
      "width",
      "backgroundColor",
      "outlineWidth",
      "outlineStyle",
    ),
  ).toEqual({
    width: await resolved(app, "width", "var(--sk-ring-glyph, 1.5rem)"),
    backgroundColor: "rgba(0, 0, 0, 0)",
    outlineWidth: "2px",
    outlineStyle: "solid",
  });
  // A row with a second title line draws a shorter second bar: 40 % of its column.
  const twoLines = app
    .locator(".sidekick-wait-row")
    .filter({ has: app.locator(".sidekick-wait-row-title:nth-of-type(2)") })
    .first();
  const bars = twoLines.locator(".sidekick-wait-row-title");
  const [first, second] = await Promise.all([
    box(bars.nth(0)),
    box(bars.nth(1)),
  ]);
  const column = await box(bars.first().locator(".."));
  expect(first.width).toBeGreaterThan(second.width);
  expect(second.width / column.width).toBeCloseTo(0.4, 1);
  expect(failures).toEqual([]);
});

test("the loading line is read by assistive technology and never drawn", async ({
  page,
}) => {
  const { app, failures } = await openWaiting(page);
  const line = app.locator(".sidekick-wait-line");
  await expect(line).toHaveCount(1);
  expect(await style(line, "position", "width", "height", "clipPath")).toEqual({
    position: "absolute",
    width: "1px",
    height: "1px",
    clipPath: "inset(50%)",
  });
  expect(failures).toEqual([]);
});

test("the rows appear after 300 ms with opacity only, and the blocks pulse until the user asks for reduced motion", async ({
  page,
}) => {
  const { app, failures } = await openWaiting(page);
  const rows = app.locator(".sidekick-wait-rows");
  await expect(rows).toHaveCount(1);
  // The reveal is an opacity animation (from 0 to 1) that waits 300 ms, so a fast answer shows no placeholder.
  expect(await style(rows, "animationName", "animationDelay")).toEqual({
    animationName: "sidekick-wait-appear",
    animationDelay: "0.3s",
  });
  const frames = await rows.evaluate((element) => {
    const animation = element
      .getAnimations()
      .find(
        (candidate) =>
          (candidate as CSSAnimation).animationName === "sidekick-wait-appear",
      );
    return (animation?.effect as KeyframeEffect | undefined)
      ?.getKeyframes()
      .map((frame) => frame.opacity);
  });
  expect(frames).toEqual(["0", "1"]);
  const block = app.locator(".sidekick-wait-block").first();
  expect((await style(block, "animationName")).animationName).toBe(
    "sidekick-wait-pulse",
  );
  expect(failures).toEqual([]);
});

test("the placeholder's blocks do not pulse with reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { app, failures } = await openWaiting(page);
  const block = app.locator(".sidekick-wait-block").first();
  await expect(block).toBeAttached();
  expect((await style(block, "animationName")).animationName).toBe("none");
  expect(failures).toEqual([]);
});

test("the timeout sentence is drawn in the note's type, muted, after the placeholder has waited", async ({
  page,
}) => {
  await page.clock.install();
  const { app, failures } = await openWaiting(page);
  await page.clock.fastForward(8500);
  const sentence = app.getByText(/Still waiting for data/);
  await expect(sentence).toBeVisible();
  expect(await style(sentence, "color", "fontSize", "lineHeight")).toEqual({
    color: await resolvedWithin(
      app.locator(".sidekick-wait"),
      "color",
      "var(--w-muted)",
    ),
    fontSize: "14px",
    lineHeight: "20px",
  });
  expect(failures).toEqual([]);
});
