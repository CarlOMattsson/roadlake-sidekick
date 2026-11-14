import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { box, resolved, style } from "./computed-style";
import { settled } from "./mcp-host-fixture";
import {
  bigAgenda,
  bigTrash,
  controlReplies,
  workReplies,
} from "./one-screen-fixtures";

// The Work room's shell measured in a real Chromium: the fullscreen frame and its foot reserve, the tab row that
// sticks under the room strip, and the band both stuck rows paint to the frame's edges. Simulated host (see
// mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture.

const insets = { top: 20, right: 4, bottom: 34, left: 12 };

async function openAgenda(
  page: Page,
  width: number,
  safeAreaInsets?: typeof insets,
) {
  const opened = await openSidekick(page, {
    width,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    replies: workReplies,
    safeAreaInsets,
  });
  await settled(opened.app);
  await expect(opened.app.locator(".sk-shell-tabs")).toBeVisible();
  return opened;
}

/** The frame body's padding on every side, as numbers. */
async function bodyPadding(app: FrameLocator) {
  const padding = await style(
    app.locator(".sk-frame__body"),
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
  );
  return Object.fromEntries(
    Object.entries(padding).map(([side, value]) => [
      side,
      Number.parseFloat(value),
    ]),
  );
}

for (const [width, side] of [
  [500, 16],
  [700, 24],
  [360, 12],
] as const) {
  test(`Work fullscreen at ${width} px: the page margin is ${side} px beside the host's safe area, and the foot keeps the reserve`, async ({
    page,
  }) => {
    const { app, failures } = await openAgenda(page, width, insets);
    expect(
      await style(app.locator(".sk-frame"), "containerType", "containerName"),
    ).toEqual({ containerType: "inline-size", containerName: "sk-frame" });
    const padding = await bodyPadding(app);
    // The top rests on half the pad, the foot on the pad and the reserve (the larger of the inset and 6rem = 96).
    expect(padding).toEqual({
      paddingTop: (width === 360 ? 16 : side) / 2 + insets.top,
      paddingRight: side + insets.right,
      paddingBottom: (width === 360 ? 16 : side) + 96,
      paddingLeft: side + insets.left,
    });
    expect(await resolved(app, "padding-top", "var(--sk-foot-reserve)")).toBe(
      "96px",
    );
    // The shell adds nothing below: the frame keeps the foot reserve.
    expect(
      (await style(app.locator(".sk-shell"), "paddingBottom")).paddingBottom,
    ).toBe("0px");
    expect(failures).toEqual([]);
  });
}

test("Work fullscreen: a host inset above 6rem takes over the foot reserve", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 500, {
    ...insets,
    bottom: 140,
  });
  expect(await resolved(app, "padding-top", "var(--sk-foot-reserve)")).toBe(
    "140px",
  );
  expect((await bodyPadding(app)).paddingBottom).toBe(16 + 140);
  expect(failures).toEqual([]);
});

test("Work fullscreen: a row title stops after 3 lines in a frame of 19rem or more, and is never cut in a narrower one", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 500);
  const body = app.locator(".sk-frame__body");
  expect(
    (await style(body, "--sk-row-title-lines"))["--sk-row-title-lines"],
  ).toBe("3");
  await page.setViewportSize({ width: 296, height: 780 });
  await page.locator("iframe").evaluate((frame) => {
    frame.style.width = "296px";
  });
  await expect
    .poll(
      async () =>
        (await style(body, "--sk-row-title-lines"))["--sk-row-title-lines"],
    )
    .toBe("none");
  expect(failures).toEqual([]);
});

test("Work fullscreen: the tab row and the room strip stay stuck under each other when the list scrolls, as one band to the frame's edges", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page, 500, insets);
  const frame = await box(app.locator(".sk-frame"));
  await app.locator("html").evaluate((html) => {
    html.scrollTop = html.scrollHeight;
  });
  const tabs = app.locator(".sk-shell-tabs");
  const bar = app.locator(".sk-rooms__bar");
  await expect.poll(async () => (await box(tabs)).y > 0).toBe(true);
  const [tabsBox, barBox] = await Promise.all([box(tabs), box(bar)]);
  // The list has scrolled, yet both rows are still in view, the tab row directly under the strip's bar.
  expect(
    await app.locator("html").evaluate((html) => html.scrollTop),
  ).toBeGreaterThan(200);
  expect(tabsBox.y).toBeCloseTo(barBox.y + barBox.height, 0);
  expect(await style(tabs, "position", "zIndex")).toEqual({
    position: "sticky",
    zIndex: "2",
  });
  // The tab row is as high as the token says, the same as the strip's tabs and tools.
  expect(tabsBox.height).toBeCloseTo(
    Number.parseFloat(await resolved(app, "width", "var(--sk-tabs-h)")),
    0,
  );
  // Both rows reach the frame's side edges (the page margin and the host inset are taken back), so while stuck they
  // paint one band of one width over the scrolling rows.
  for (const stuck of [tabsBox, barBox]) {
    expect(stuck.x).toBeCloseTo(frame.x, 0);
    expect(stuck.width).toBeCloseTo(frame.width, 0);
  }
  expect(failures).toEqual([]);
});

test("Kontroll: the segmented tabs are 48 high and stick under the room strip when the rows scroll", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 500,
    theme: "light",
    tool: "list_trash",
    result: bigTrash,
    replies: controlReplies,
  });
  await settled(app);
  const group = app.locator(".sidekick-control .sk-segmented").first();
  await expect(group).toBeVisible();
  for (const option of await group.locator(".sk-segmented__option").all())
    expect((await box(option)).height).toBe(48);
  await app.locator("html").evaluate((html) => {
    html.scrollTop = html.scrollHeight;
  });
  const bar = app.locator(".sk-rooms__bar");
  await expect.poll(async () => (await box(group)).y).toBeGreaterThan(0);
  expect(
    await app.locator("html").evaluate((html) => html.scrollTop),
  ).toBeGreaterThan(200);
  const [groupBox, barBox] = await Promise.all([box(group), box(bar)]);
  expect(await style(group, "position")).toEqual({ position: "sticky" });
  expect(groupBox.y).toBeCloseTo(barBox.y + barBox.height, 0);
  expect(failures).toEqual([]);
});
