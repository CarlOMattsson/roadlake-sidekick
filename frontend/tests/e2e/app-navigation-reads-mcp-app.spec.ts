import { test, expect } from "@playwright/test";
import {
  getTaskFromEntry,
  ok,
  opening,
  task,
  workItem,
} from "./sidekick-domain-fixtures";
import {
  widths,
  themes,
  openSidekick,
  strip,
  room,
  back,
  h2,
  picker,
  isNarrow,
  goRoom,
  expectCurrentRoom,
  doneTask,
  serverRemembersDone,
  callNames,
  openTask,
  chooseView,
} from "./app-navigation-fixtures";

// A room read again after a write elsewhere, scroll kept across a trip, the strip's size and the keyboard.
// SIMULATED host; see app-navigation-mcp-app.spec.ts for the rule they share (one visible Back).

for (const width of widths) {
  for (const theme of themes) {
    const suffix = `${width} px, ${theme}`;

    test(`agenda to a task, Done, Back: the agenda under it is read again and no longer lists the task (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: { items: [workItem(task)], filters: {}, next_cursor: null },
        replies: {
          get_work_agenda: ok({
            items: [workItem(task)],
            filters: {},
            next_cursor: null,
          }),
          update_task: ok({ task: doneTask }),
        },
      });
      await expect(app.getByText(/Försenade \(1\)/)).toBeVisible();
      await openTask(app).click();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await serverRemembersDone(page);
      await app.getByRole("button", { name: "Markera klar" }).click();
      await expect
        .poll(async () => (await callNames(page)).includes("update_task"))
        .toBe(true);
      await back(app).click();
      await expect(back(app)).toHaveCount(0);
      // Same view, no manual refresh: the overdue row is gone.
      await expect(app.getByText("Inget på agendan.")).toBeVisible();
      await expect(app.getByText(/Försenade/)).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`Journal to Anna to her task, Done, Back: Anna shows the task as done (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_entry",
        result: opening.journalEntry,
        replies: {
          update_task: ok({ task: doneTask }),
          get_task: getTaskFromEntry,
        },
      });
      await app
        .getByRole("button", { name: "Anna Andersson", exact: true })
        .click();
      // The task row's ring says "Att göra" (a labelled image); the row has no "Status:" text.
      await expect(app.getByRole("img", { name: "Att göra" })).toBeVisible();
      await openTask(app).click();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await serverRemembersDone(page);
      await app.getByRole("button", { name: "Markera klar" }).click();
      await expect
        .poll(async () => (await callNames(page)).includes("update_task"))
        .toBe(true);
      await back(app).click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await expect(app.getByText("Klar", { exact: true })).toBeVisible();
      await expect(app.getByRole("img", { name: "Att göra" })).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`a scrolled board keeps its scroll through a trip to another room, and the strip stays tappable (${suffix})`, async ({
      page,
    }) => {
      const many = Array.from({ length: 25 }, (_, index) => ({
        ...workItem({
          ...task,
          id: `019f0000-0000-7000-8000-0000000005${String(index).padStart(2, "0")}`,
          title: `Pågående ${index + 1}`,
          status: "in_progress",
        }),
        agenda_group: "later",
      }));
      const board = {
        columns: { todo: [], in_progress: many, blocked: [], completed: [] },
        next_cursor: null,
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_board",
        result: board,
        replies: { get_work_board: ok(board) },
      });
      await chooseView(app, "Status", width);
      const scroll = () =>
        app
          .locator("html")
          .evaluate(() => document.scrollingElement!.scrollTop);
      // 600: the board's rows are lower, so 900 is past its end at 375 px.
      await app
        .locator("html")
        .evaluate(() => (document.scrollingElement!.scrollTop = 600));
      expect(await scroll()).toBe(600);
      // The view tabs of the board rest below the strip: the strip's room control is what a tap hits. That is the
      // second tab, or the picker when the labels do not fit (the tabs are then hidden).
      const hit = await app.locator("html").evaluate(() => {
        const target =
          document.querySelector<HTMLElement>(".sk-rooms .sk-pick") ??
          document.querySelectorAll<HTMLElement>(".sk-rooms__tab")[1]!;
        const box = target.getBoundingClientRect();
        const top = document.elementFromPoint(
          box.left + box.width / 2,
          box.top + box.height / 2,
        );
        return target.contains(top);
      });
      expect(hit).toBe(true);
      await goRoom(app, "Dagbok");
      await expect(app.getByText("Lunch med Anna").first()).toBeVisible();
      await goRoom(app, "Arbete");
      await expect(app.getByRole("region", { name: "Pågår" })).toBeVisible();
      await expect.poll(scroll).toBe(600);
      expect(failures).toEqual([]);
    });

    test(`the strip fits without sideways scroll and keeps 44 px targets (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: { items: [], filters: {}, next_cursor: null },
      });
      await expect(strip(app)).toBeVisible();
      // The strip is 40 px high and the cell 32 px; the tap target is the cell plus its ::after
      // (inset -6 px top and bottom, designsystem §3), so the target is measured with that inset added and stays >= 44.
      const measure = await app.locator("body").evaluate((body) => ({
        scrollWidth: body.scrollWidth,
        viewport: window.innerWidth,
        stripHeight:
          document.querySelector(".sk-rooms")?.getBoundingClientRect().height ??
          0,
        targets: Array.from(
          document.querySelectorAll(".sk-rooms__tab"),
          (tab) => {
            const after = getComputedStyle(tab, "::after");
            return (
              tab.getBoundingClientRect().height -
              parseFloat(after.top) -
              parseFloat(after.bottom)
            );
          },
        ),
      }));
      expect(measure.scrollWidth).toBeLessThanOrEqual(measure.viewport);
      expect(Math.abs(measure.stripHeight - 40)).toBeLessThanOrEqual(0.5);
      expect(measure.targets).toHaveLength(4);
      for (const target of measure.targets)
        expect(target).toBeGreaterThanOrEqual(43.5);
      expect(failures).toEqual([]);
    });

    test(`keyboard: arrows move along the strip and focus lands in the new room, and on the heading after Back (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: { items: [], filters: {}, next_cursor: null },
      });
      if (await isNarrow(app)) {
        // The picker stands in for the strip: Enter opens its menu on the chosen room, ArrowDown moves on.
        await picker(app).focus();
        await page.keyboard.press("Enter");
        await expect(
          app.getByRole("menuitemradio", { name: "Arbete", exact: true }),
        ).toBeFocused();
        await page.keyboard.press("ArrowDown");
        await expect(
          app.getByRole("menuitemradio", { name: "Dagbok", exact: true }),
        ).toBeFocused();
      } else {
        await room(app, "Arbete").focus();
        await page.keyboard.press("ArrowRight");
        await expect(room(app, "Dagbok")).toBeFocused();
      }
      await page.keyboard.press("Enter");
      await expect(
        app.locator(
          '[data-room="journal"] :focus, [data-room="journal"]:focus',
        ),
      ).toHaveCount(1);
      await expectCurrentRoom(app, "Dagbok");
      // A step in and Back also move focus into the layer that is shown, not to the page.
      await app
        .getByRole("button", { name: /Lunch med Anna/ })
        .first()
        .click();
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await expect(app.locator('[data-room="journal"] :focus')).toHaveCount(1);
      await back(app).click();
      await expect(app.locator('[data-room="journal"] :focus')).toHaveCount(1);
      expect(failures).toEqual([]);
    });
  }
}
