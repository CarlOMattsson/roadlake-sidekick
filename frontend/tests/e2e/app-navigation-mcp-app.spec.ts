import { test, expect } from "@playwright/test";
import { getTaskFromEntry, opening } from "./sidekick-domain-fixtures";
import { deliverToolResult, setHostContext } from "./mcp-host-fixture";
import {
  widths,
  themes,
  openSidekick,
  strip,
  back,
  h2,
  goRoom,
  expectCurrentRoom,
  expectRoomNames,
  callNames,
  openTask,
  editTask,
  chooseView,
} from "./app-navigation-fixtures";

// Navigation between the rooms of the Sidekick app (docs/explanation/architecture/mcp-apps.md, "Entry, navigation and durable context";
// journal to contact to task, shopping state, fullscreen fallbacks) in the SIMULATED host. Its siblings:
// app-navigation-control (Control and where the card opens), app-navigation-inline (the card and the full view),
// app-navigation-reads (re-reads, scroll, keyboard).
// The host proxies tool calls (serverTools) and takes messages. The app runs in Swedish, the default.
// Every test runs at 375 and 320 px, light and dark.
// One rule runs through all of them: exactly ONE visible Back ("Tillbaka") in the full view, and it
// goes one step at a time through the shell's stack.
// Not covered here: an approved journal draft that became a task (the draft review needs its own
// fixture; the dirty mark for finalize_journal_draft and the re-read are unit-tested), two cards
// at once (needs two iframes; supersession is unit-tested), voice, and anything that needs the real model.

for (const width of widths) {
  for (const theme of themes) {
    const suffix = `${width} px, ${theme}`;

    test(`journal entry to Anna to her task, edit it, Back one step at a time; Work shows the edit (${suffix})`, async ({
      page,
    }) => {
      const { app, failures, networkRequests } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_entry",
        result: opening.journalEntry,
        replies: { get_task: getTaskFromEntry },
      });
      await expectRoomNames(app, ["Arbete", "Dagbok", "Kontakter", "Inköp"]);
      // The entry is a first step above the journal's day: Back is there from the start.
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      // Visit Work first, so it has been read once and the later edit must reach it.
      await goRoom(app, "Arbete");
      // The agenda's row (the entry's Task chip, in the Journal layer under it, is named "Öppna uppgiften …").
      await expect(openTask(app)).toBeVisible();
      await expect(back(app)).toHaveCount(0);
      await goRoom(app, "Dagbok");
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await app
        .getByRole("button", { name: "Anna Andersson", exact: true })
        .click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await expectCurrentRoom(app, "Dagbok");
      await expect(back(app)).toHaveCount(1);
      await openTask(app).click();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      // One Back, of one look and in one place, and none of the rooms' own.
      await expect(back(app)).toHaveCount(1);
      await expect(app.locator(".work-back, .journal-back")).toHaveCount(0);
      await editTask(app);
      await app.getByLabel("Titel").fill("Ring Anna idag");
      await app.getByRole("button", { name: "Spara" }).click();
      await expect(app.getByText("Sparat", { exact: true })).toBeVisible();
      // Back goes exactly one step: task, Anna, the entry, the day.
      await back(app).click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await back(app).click();
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await back(app).click();
      await expect(back(app)).toHaveCount(0);
      await expect(
        app.getByRole("button", { name: /Lunch med Anna/ }),
      ).toBeVisible();
      await expectCurrentRoom(app, "Dagbok");
      // Work was written to from the Journal pane: it reads again, with no manual refresh.
      await goRoom(app, "Arbete");
      await expect(
        app.getByText("Ring Anna idag", { exact: true }),
      ).toBeVisible();
      expect(failures).toEqual([]);
      expect(networkRequests()).toBe(0);
    });

    test(`a press on the active room goes to its root from any depth (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_entry",
        result: opening.journalEntry,
        replies: { get_task: getTaskFromEntry },
      });
      await app
        .getByRole("button", { name: "Anna Andersson", exact: true })
        .click();
      await openTask(app).click();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await goRoom(app, "Dagbok");
      await expect(back(app)).toHaveCount(0);
      await expect(
        app.getByRole("button", { name: /Lunch med Anna/ }),
      ).toBeVisible();
      expect(failures).toEqual([]);
    });

    test(`board column survives a trip to Contacts, an edit there and a re-read (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_board",
        result: opening.workBoard,
      });
      await chooseView(app, "Status", width);
      await expect(app.getByRole("region", { name: "Pågår" })).toBeVisible();
      await goRoom(app, "Kontakter");
      await app
        .getByRole("button", { name: "Anna Andersson", exact: true })
        .click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await openTask(app).click();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await editTask(app);
      await app.getByLabel("Titel").fill("Ring Anna idag");
      await app.getByRole("button", { name: "Spara" }).click();
      await expect(app.getByText("Sparat", { exact: true })).toBeVisible();
      const reads = async () =>
        (await callNames(page)).filter((name) => name === "get_work_board")
          .length;
      const before = await reads();
      await goRoom(app, "Arbete");
      // Work was written to: it reads again, and stays on the board's In progress column.
      await expect(app.getByRole("region", { name: "Pågår" })).toBeVisible();
      await expect.poll(reads).toBeGreaterThan(before);
      await expect(app.getByRole("region", { name: "Pågår" })).toBeVisible();
      await expect(back(app)).toHaveCount(0);
      // The Contacts room kept its stack: Back there goes one step, to Anna.
      await goRoom(app, "Kontakter");
      await expect(h2(app, "Ring Anna idag")).toBeVisible();
      await back(app).click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      expect(failures).toEqual([]);
    });

    test(`shopping keeps what was bought across a trip to Work (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_shopping_list",
        result: opening.shoppingList,
      });
      // The ring marks an item bought; the row opens its change form.
      await app
        .getByRole("button", { name: /^Markera .* som köpt$/ })
        .first()
        .click();
      // The bought row stays among the open ones while its Ångra holds; its ring now offers to undo.
      await expect(
        app.getByRole("button", { name: /^Markera .* som ej köpt$/ }),
      ).toHaveCount(1);
      const reads = async () =>
        (await callNames(page)).filter((name) => name === "get_shopping_list")
          .length;
      const before = await reads();
      await goRoom(app, "Arbete");
      await expect(
        app.getByText("Ring Anna om offerten", { exact: true }),
      ).toBeVisible();
      await goRoom(app, "Inköp");
      await expect(
        app.getByRole("button", { name: /^Markera .* som ej köpt$/ }),
      ).toHaveCount(1);
      // The room stayed mounted and was not read again.
      expect(await reads()).toBe(before);
      expect(failures).toEqual([]);
    });

    test(`rooms opened from the strip read for themselves (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: { items: [], filters: {}, next_cursor: null },
      });
      await goRoom(app, "Inköp");
      // Shopping starts with the lists, not with a form and a drop-down: a single list opens at once.
      await expect(h2(app, "IKEA someday")).toBeVisible();
      await expect(app.getByLabel("Listans namn")).toHaveCount(0);
      await goRoom(app, "Dagbok");
      await expect(app.getByText("Lunch med Anna").first()).toBeVisible();
      await goRoom(app, "Kontakter");
      await expect(
        app.getByRole("button", { name: "Anna Andersson", exact: true }),
      ).toBeVisible();
      // Contacts is Contacts everywhere: its region and its heading are not called Work.
      await expect(
        app.locator('[data-room="contacts"]').getByRole("heading", {
          level: 1,
          name: "Kontakter",
          includeHidden: true,
        }),
      ).toHaveCount(1);
      expect(failures).toEqual([]);
    });

    test(`a host without fullscreen: no strip inline, strip in the expanded view, new result back to the card (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_day",
        result: opening.journalDay,
        displayMode: "inline",
        availableDisplayModes: ["inline"],
      });
      await expect(app.locator(".sidekick-journal")).toBeVisible();
      await expect(strip(app)).toHaveCount(0);
      const height = await app
        .locator(".sidekick-journal")
        .evaluate((root) => root.getBoundingClientRect().height);
      expect(height).toBeLessThanOrEqual(560);
      await app.getByRole("button", { name: /^(Öppna|Visa alla)/ }).click();
      await expect(strip(app)).toBeVisible();
      await deliverToolResult(page, opening.journalDay);
      await expect(strip(app)).toHaveCount(0);
      await expect(
        app.getByRole("button", { name: /^(Öppna|Visa alla)/ }),
      ).toBeVisible();
      expect(failures).toEqual([]);
    });

    test(`the expanded view of a host without fullscreen can be folded in again (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_day",
        result: opening.journalDay,
        displayMode: "inline",
        availableDisplayModes: ["inline"],
      });
      await app.getByRole("button", { name: /^(Öppna|Visa alla)/ }).click();
      await expect(strip(app)).toBeVisible();
      await app.getByRole("button", { name: "Fäll ihop" }).click();
      await expect(strip(app)).toHaveCount(0);
      await expect(app.locator(".sidekick-journal")).toBeVisible();
      await expect(app.getByRole("button", { name: "Fäll ihop" })).toHaveCount(
        0,
      );
      expect(failures).toEqual([]);
    });

    test(`a host that grants fullscreen but never says so: its inline report ends the expanded view (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_day",
        result: opening.journalDay,
        displayMode: "inline",
      });
      await app.getByRole("button", { name: /^(Öppna|Visa alla)/ }).click();
      await expect(strip(app)).toBeVisible();
      // The host closes its fullscreen and reports inline, a mode the app already believed it was in.
      await setHostContext(page, { displayMode: "inline" });
      await expect(strip(app)).toHaveCount(0);
      await expect(app.locator(".sidekick-journal")).toBeVisible();
      expect(failures).toEqual([]);
    });
  }
}
