import { expect, test } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { box, resolved, style } from "./computed-style";
import { settled } from "./mcp-host-fixture";
import { bigAgenda, fullTask, workReplies } from "./one-screen-fixtures";

// The inline Work cards (inline-summary.css) measured in a real Chromium from computed style and boxes, instead of read
// out of the stylesheet. Simulated host (see mcp-host-fixture.ts), not a real Claude or Android host: every tool answer
// is a fixture.

test("Inline agenda card: a row is the title and the chevron on one line with the meta under them, as tall as a 44 px target", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    displayMode: "inline",
    replies: workReplies,
  });
  await settled(app);
  const card = app.locator(".work-compact-card");
  await expect(card).toBeVisible();
  const open = app.locator(".work-compact-open").first();
  await expect(open).toBeVisible();
  const { display, gridTemplateColumns } = await style(
    open,
    "display",
    "gridTemplateColumns",
  );
  expect(display).toBe("grid");
  const tracks = gridTemplateColumns!.split(" ").map(Number.parseFloat);
  expect(tracks).toHaveLength(2);
  const [titleBox, chevronBox, metaBox, openBox] = await Promise.all([
    box(open.locator(".work-compact-row-title")),
    box(open.locator(".work-open-chevron")),
    box(open.locator(".work-compact-row-meta")),
    box(open),
  ]);
  // The title and the chevron share the first line: the chevron is the narrow track at the end, beside the title.
  expect(tracks[1]).toBeCloseTo(chevronBox.width, 0);
  expect(chevronBox.x).toBeGreaterThanOrEqual(titleBox.x + titleBox.width - 1);
  expect(chevronBox.y).toBeLessThan(titleBox.y + titleBox.height);
  // The meta line lies under both.
  expect(metaBox.y).toBeGreaterThanOrEqual(titleBox.y + titleBox.height - 1);
  expect(openBox.height).toBeGreaterThanOrEqual(44);
  expect(failures).toEqual([]);
});

test("Inline cards have no inner scroll and no height cap of their own", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    displayMode: "inline",
    replies: workReplies,
  });
  await settled(app);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  const offenders = await app
    .locator(".work-compact-card, .work-compact-card [class*='work-compact']")
    .evaluateAll((elements) =>
      elements
        .filter((element) => {
          const computed = getComputedStyle(element);
          return (
            [computed.overflowX, computed.overflowY].some(
              (value) => value === "auto" || value === "scroll",
            ) || computed.maxHeight !== "none"
          );
        })
        .map((element) => element.getAttribute("class") ?? ""),
    );
  expect(offenders).toEqual([]);
  expect(failures).toEqual([]);
});

test("Inline Task card: Mark as done and Open are text buttons of at least the 44 px tap floor", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_task",
    result: { task: { ...fullTask, status: "todo" } },
    displayMode: "inline",
    availableDisplayModes: ["inline"],
    replies: workReplies,
  });
  await settled(app);
  const actions = await app.locator(".work-compact-action").all();
  expect(actions.length).toBeGreaterThanOrEqual(2);
  const floor = await resolved(app, "min-height", "var(--sk-tap)");
  expect(floor).toBe("44px");
  for (const action of actions) {
    await expect(action).toBeVisible();
    // The primary action takes the larger 48 px floor of .sk-btn--primary; none is below the tap floor.
    expect(
      Number.parseFloat((await style(action, "minHeight")).minHeight ?? ""),
    ).toBeGreaterThanOrEqual(44);
    expect((await box(action)).height).toBeGreaterThanOrEqual(44);
    expect(await action.getAttribute("style")).toBeNull();
  }
  // The Open action is the family's open text button with its chevron, beside the primary Done.
  const openAction = app.locator(".work-compact-action.sk-btn--open");
  await expect(openAction).toHaveCount(1);
  await expect(openAction.locator("svg")).toHaveCount(1);
  expect(failures).toEqual([]);
});
