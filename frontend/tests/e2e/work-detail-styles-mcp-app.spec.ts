import { expect, test } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { box, pseudoStyle, resolved, style } from "./computed-style";
import { settled } from "./mcp-host-fixture";
import { fullTask, workReplies } from "./one-screen-fixtures";

// The Work room's detail views measured in a real Chromium from computed style and boxes. Simulated host (see
// mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture.

test("Task view: no frame of its own, the status and due date are property chips, Markera klar is a compact primary and each Step is a 48 px row with 6 px of air", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 320,
    theme: "light",
    tool: "get_task",
    result: { task: fullTask },
    replies: workReplies,
  });
  await settled(app);
  const task = app.locator(".work-task").first();
  await expect(task).toBeVisible();
  expect(
    await style(task, "paddingTop", "paddingLeft", "borderTopWidth"),
  ).toEqual({
    paddingTop: "0px",
    paddingLeft: "0px",
    borderTopWidth: "0px",
  });
  // The status is a property chip, not a radio group.
  await expect(app.getByRole("radiogroup")).toHaveCount(0);
  const chips = app.locator("button.work-prop-chip");
  expect(await chips.count()).toBeGreaterThan(0);
  for (const chip of await chips.all()) {
    await expect(chip).toHaveClass(/sk-chip/);
    expect((await box(chip)).height).toBeGreaterThanOrEqual(44);
  }
  // The family's compact primary: as wide as its text, one line, 44 high like the chips beside it, last of its row.
  const done = app.locator("button.work-task-done").first();
  await expect(done).toBeVisible();
  const [doneBox, rowBox] = await Promise.all([
    box(done),
    box(done.locator("xpath=..")),
  ]);
  expect(doneBox.width).toBeLessThan(rowBox.width - 1);
  expect(doneBox.height).toBeGreaterThanOrEqual(44);
  expect((await style(done, "whiteSpace")).whiteSpace).toBe("nowrap");
  expect(
    await done.evaluate(
      (button) => button.parentElement?.lastElementChild === button,
    ),
  ).toBe(true);
  // A Step is a row of the row template: at least 48, the row padding over and under its text.
  const step = app
    .locator(".work-steps label, .work-steps .work-step-read")
    .first();
  await expect(step).toBeVisible();
  expect((await box(step)).height).toBeGreaterThanOrEqual(48);
  const air = await resolved(app, "padding-top", "var(--sk-row-pad)");
  expect(await style(step, "paddingTop", "paddingBottom")).toEqual({
    paddingTop: air,
    paddingBottom: air,
  });
  expect(failures).toEqual([]);
});

test("Task view: the chosen chip of a property's choices has the 2 px outline in the text colour, the selected fill and a tick, and nothing moves", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_task",
    result: { task: fullTask },
    replies: workReplies,
  });
  await settled(app);
  await app
    .locator("button.work-prop-chip", {
      has: app.locator(".work-card-priority"),
    })
    .click();
  const chosen = app.locator('.sk-chip[aria-pressed="true"]');
  await expect(chosen).toBeVisible();
  const other = app.locator('.sk-chip[aria-pressed="false"]').first();
  expect(await style(chosen, "backgroundColor", "fontWeight")).toEqual({
    backgroundColor: await resolved(
      app,
      "background-color",
      "var(--sk-selected-bg)",
    ),
    fontWeight: await resolved(app, "font-weight", "var(--sk-weight-semibold)"),
  });
  // The 1 px edge plus the rest of the 2 px contour inside it: the outline is drawn without growing the chip.
  expect(await style(chosen, "borderTopColor", "boxShadow")).toEqual({
    borderTopColor: await resolved(
      app,
      "border-top-color",
      "var(--sk-selected-line)",
    ),
    boxShadow: await resolved(
      app,
      "box-shadow",
      "inset 0 0 0 calc(var(--sk-selected-width) - var(--sk-hairline)) var(--sk-selected-line)",
    ),
  });
  expect((await box(chosen)).height).toBeCloseTo((await box(other)).height, 0);
  // The tick before the text is a mask of the family's check mark.
  const tick = await pseudoStyle(
    chosen,
    "::before",
    "content",
    "width",
    "height",
  );
  expect(tick.content).not.toBe("none");
  expect(Number.parseFloat(tick.width ?? "0")).toBeGreaterThan(0);
  expect(
    await chosen.evaluate((chip) =>
      getComputedStyle(chip, "::before").getPropertyValue("-webkit-mask-image"),
    ),
  ).toContain("url(");
  expect(failures).toEqual([]);
});

test("Task view: the tip under the Steps is meta type and muted until a Step's menu has been opened, then it is not drawn", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 375,
    theme: "light",
    tool: "get_task",
    result: { task: fullTask },
    replies: workReplies,
  });
  await settled(app);
  const tip = app.locator(".work-row-tip:not([hidden])");
  await expect(tip).toBeVisible();
  expect((await style(tip, "color")).color).toBe(
    await resolved(app, "color", "var(--sk-muted)"),
  );
  const step = app.locator(".work-steps li").nth(5);
  await step.click({ button: "right" });
  await expect(tip).toBeHidden();
  expect((await style(tip, "display")).display).toBe("none");
  expect(failures).toEqual([]);
});

test("Task view: a long place wraps inside its chip, the ⌄ stays at its end, and the chip is 44 to tap", async ({
  page,
}) => {
  const longPlace = {
    ...fullTask,
    project_title:
      "Fastighetsförvaltningsprojektet för Bergströms Byggnadsentreprenad AB 2026",
  };
  const { app, failures } = await openSidekick(page, {
    width: 320,
    theme: "light",
    tool: "get_task",
    result: { task: longPlace },
    replies: {
      ...workReplies,
      get_task: { structuredContent: { task: longPlace } },
    },
  });
  await settled(app);
  const chip = app.getByRole("button", { name: /^Ändra plats/ });
  await expect(chip).toBeVisible();
  expect(
    await style(chip, "whiteSpace", "flexWrap", "maxWidth", "minWidth"),
  ).toEqual({
    whiteSpace: "normal",
    flexWrap: "nowrap",
    maxWidth: "100%",
    minWidth: "0px",
  });
  const [chipBox, glyph, text] = await Promise.all([
    box(chip),
    box(chip.locator("svg")),
    box(chip.locator("span").first()),
  ]);
  expect(chipBox.height).toBeGreaterThanOrEqual(44);
  // Wrapped onto more than one line, the text stays inside the chip and the glyph stays at its end.
  expect(chipBox.height).toBeGreaterThan(48);
  expect(text.x + text.width).toBeLessThanOrEqual(glyph.x + 1);
  expect(chipBox.x + chipBox.width).toBeLessThanOrEqual(320);
  expect(
    await style(chip.locator("span").first(), "minWidth", "overflowWrap"),
  ).toEqual({ minWidth: "0px", overflowWrap: "anywhere" });
  expect((await style(chip.locator("svg"), "flexShrink")).flexShrink).toBe("0");
  expect(failures).toEqual([]);
});
