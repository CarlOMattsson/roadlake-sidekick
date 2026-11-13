import { expect, test } from "@playwright/test";
import { bigAgenda, FIXTURE_NOW, workReplies } from "./one-screen-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  setHostReply,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// "Flytta N försenade till imorgon" in a real Chromium on the simulated host (mcp-host-fixture.ts), not a real Claude or
// Android host: every tool answer is a fixture and the network is closed. The line after the move ("5 flyttade till
// imorgon · Ångra") scrolls into view and takes focus; at a phone's width it must stand below the stuck tab row, not
// under it.

const isOverdue = (item: object) =>
  (item as { agenda_group?: string }).agenda_group === "overdue";
const overdue = bigAgenda.items.filter(isOverdue);
const rest = bigAgenda.items.filter((item) => !isOverdue(item));

for (const theme of ["light", "dark"] as const)
  test(`Agenda ${theme}: after Flytta the receipt and Ångra stand below the stuck tab row at 375 px`, async ({
    page,
  }) => {
    await page.clock.setFixedTime(FIXTURE_NOW);
    const { app, failures, networkRequests } = await openSimulatedApp(page, {
      resource: readBuiltApp("sidekick", "sv"),
      width: 375,
      height: 812,
      hostContext: {
        locale: "sv",
        theme,
        displayMode: "fullscreen",
        availableDisplayModes: ["inline", "fullscreen"],
      },
      replies: {
        ...workReplies,
        reschedule_tasks: {
          structuredContent: {
            count: overdue.length,
            tasks: overdue.map((item) => ({
              id: item.id,
              version: 2,
              due_at: FIXTURE_NOW.toISOString(),
            })),
          },
        },
      },
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, bigAgenda);
    await settled(app);

    const move = app.getByRole("button", {
      name: `Flytta ${overdue.length} försenade till imorgon`,
    });
    await expect(move).toBeVisible();
    // The list is read again without the moved Tasks, so the line stands above a shorter list.
    await setHostReply(page, "get_work_agenda", {
      structuredContent: { items: rest, next_cursor: null },
    });
    // The owner is down the list when the move is confirmed: the line then lies above the viewport and the app
    // scrolls it back into view.
    const frameScroll = app.locator("html");
    await frameScroll.evaluate(() => window.scrollTo(0, 400));
    await move.click();
    await app.getByRole("button", { name: "Flytta", exact: true }).click();

    const undo = app.getByRole("button", { name: "Ångra" });
    await expect(undo).toBeVisible();
    await expect(
      app.getByText(`${overdue.length} flyttade till imorgon`),
    ).toBeVisible();
    await settled(app);

    const tabs = await app.locator(".sk-shell-tabs").boundingBox();
    const undoBox = await undo.boundingBox();
    expect(tabs, "the tab row has a box").not.toBeNull();
    expect(undoBox, "Ångra has a box").not.toBeNull();
    expect(undoBox!.y).toBeGreaterThanOrEqual(tabs!.y + tabs!.height);
    expect(undoBox!.y + undoBox!.height).toBeLessThanOrEqual(812);
    expect(networkRequests()).toBe(0);
    expect(failures).toEqual([]);
  });
