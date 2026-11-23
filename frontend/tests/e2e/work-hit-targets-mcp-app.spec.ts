import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { goRoom, openSidekick, room } from "./app-navigation-fixtures";
import { effectiveTargetSize, settled } from "./mcp-host-fixture";
import { opening } from "./sidekick-domain-fixtures";

// Touch targets of the Work room measured in a real Chromium: the board's Status ring takes its whole column in the
// row's height whatever the text size, the room strip's tabs are 48 high, and Kontakter's + sits beside the search
// field, not on it. Simulated host (see mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is
// a fixture. The text size is the root font size of the frame, which the app's rem sizes follow.

const TARGET_PX = 48;

async function openBoard(page: Page, textScale: number) {
  const opened = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "get_work_board",
    result: opening.workBoard,
  });
  await settled(opened.app);
  if (textScale !== 1)
    await opened.app.locator("html").evaluate((html, scale) => {
      html.style.fontSize = `${16 * scale}px`;
    }, textScale);
  await settled(opened.app);
  return opened;
}

/** Whether every point of the ring's column across the row, sampled every 4 px, hits the ring button. */
async function columnHitsRing(app: FrameLocator): Promise<{
  rowHeight: number;
  misses: number;
  samples: number;
  width: number;
}> {
  return app
    .locator("li.work-card")
    .first()
    .evaluate((row) => {
      const done = row.querySelector<HTMLElement>("button.work-card-done")!;
      const box = done.getBoundingClientRect();
      const rowBox = row.getBoundingClientRect();
      let misses = 0;
      let samples = 0;
      const centre = box.left + box.width / 2;
      for (let y = rowBox.top + 1; y < rowBox.bottom - 1; y += 4) {
        samples += 1;
        const hit = row.ownerDocument.elementFromPoint(centre, y);
        if (!hit?.closest("button.work-card-done")) misses += 1;
      }
      return {
        rowHeight: rowBox.height,
        misses,
        samples,
        width: box.width,
      };
    });
}

for (const scale of [1, 2]) {
  test(`Board: the Status ring's column is at least 44 wide and hits across the row at ${scale * 100} % text`, async ({
    page,
  }) => {
    const { app, failures } = await openBoard(page, scale);
    const ring = await columnHitsRing(app);
    expect(ring.samples).toBeGreaterThan(5);
    expect(ring.width).toBeGreaterThanOrEqual(44);
    expect(ring.rowHeight).toBeGreaterThanOrEqual(TARGET_PX);
    // Every sampled point under the ring, from the row's top to its foot, marks the Task done.
    expect(ring.misses).toBe(0);
    // The ring's glyph sits on the middle of the title's first line.
    const [glyph, title] = await Promise.all([
      app
        .locator("li.work-card button.work-card-done svg")
        .first()
        .boundingBox(),
      app
        .locator("li.work-card .work-card-head > button:not(.work-card-done)")
        .first()
        .boundingBox(),
    ]);
    expect(glyph && title).toBeTruthy();
    expect(
      Math.abs(glyph!.y + glyph!.height / 2 - (title!.y + 12 * scale)),
    ).toBeLessThanOrEqual(8 * scale);
    expect(failures).toEqual([]);
  });
}

test("Room strip: each room's target is 48 high; Kontakter's + stands beside the search field and keeps a 48 wide target", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 500,
    theme: "light",
    tool: "get_work_board",
    result: opening.workBoard,
  });
  await settled(app);
  const tab = room(app, "Dagbok");
  await expect(tab).toBeVisible();
  expect((await effectiveTargetSize(tab))?.height).toBe(TARGET_PX);
  await goRoom(app, "Kontakter");
  const search = app.locator(".work-contacts-search");
  const add = app.locator(".work-contacts-add");
  await expect(search).toBeVisible();
  const [searchBox, addBox, addTarget] = await Promise.all([
    search.boundingBox(),
    add.boundingBox(),
    effectiveTargetSize(add),
  ]);
  expect(searchBox && addBox).toBeTruthy();
  // The + does not overlap the search field, and the field is 48 high with its surface inside.
  expect(addBox!.x).toBeGreaterThanOrEqual(
    searchBox!.x + searchBox!.width - 0.5,
  );
  expect(searchBox!.height).toBe(TARGET_PX);
  expect(addTarget?.width).toBeGreaterThanOrEqual(TARGET_PX);
  expect(failures).toEqual([]);
});
