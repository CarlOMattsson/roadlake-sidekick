import { expect, test } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { box, resolved, style } from "./computed-style";
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
