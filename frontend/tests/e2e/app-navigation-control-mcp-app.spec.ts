import { test, expect } from "@playwright/test";
import { anna, ok, opening, task } from "./sidekick-domain-fixtures";
import { setHostContext } from "./mcp-host-fixture";
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
  openTask,
  chooseView,
} from "./app-navigation-fixtures";

// Control (Kontroll) as a step above a room, a token without journal access, and where a card opens the full view.
// SIMULATED host; see app-navigation-mcp-app.spec.ts for the rule they share (one visible Back).

for (const width of widths) {
  for (const theme of themes) {
    const suffix = `${width} px, ${theme}`;

    test(`Kontroll keeps the room strip with no room chosen; "‹ Arbete" leads back (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "list_trash",
        result: { items: [], has_more: false },
        replies: { list_trash: ok({ items: [], has_more: false }) },
      });
      // Control is a step above the room it was opened from (Arbete, nav-state).
      // Control keeps the room strip, but no room is marked there (no tab carries aria-current). The one Back row
      // "‹ Arbete" is the way out; the title "Minne och kontroll" under it says where the user is.
      await expect(strip(app)).toBeVisible();
      await expect(strip(app).locator("[aria-current]")).toHaveCount(0);
      await expect(h2(app, "Minne och kontroll")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await expect(
        app.getByRole("button", { name: "Tillbaka till Arbete" }),
      ).toHaveCount(1);
      await expect(back(app)).toContainText("Arbete");
      await expect(back(app)).not.toContainText("Minne och kontroll");
      // The visible title stands under the Back row, and the tabs under the title.
      const backBox = await back(app).boundingBox();
      const titleBox = await h2(app, "Minne och kontroll").boundingBox();
      expect(titleBox!.y).toBeGreaterThanOrEqual(
        backBox!.y + backBox!.height - 1,
      );
      // "‹ Arbete" leads back to Arbete, one step, and Control is gone.
      await back(app).click();
      await expect(h2(app, "Minne och kontroll")).toHaveCount(0);
      await expect(back(app)).toHaveCount(0);
      await expectCurrentRoom(app, "Arbete");
      await goRoom(app, "Dagbok");
      await expectCurrentRoom(app, "Dagbok");
      const sideways = await app
        .locator("body")
        .evaluate((body) => body.scrollWidth <= window.innerWidth);
      expect(sideways).toBe(true);
      expect(failures).toEqual([]);
    });

    test(`Kontroll: the origin room's tab in the strip takes Control back to that room (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "list_trash",
        result: { items: [], has_more: false },
        replies: { list_trash: ok({ items: [], has_more: false }) },
      });
      // A press on Arbete's tab while Control is open goes back to Arbete, as "‹ Arbete" does.
      await expect(strip(app)).toBeVisible();
      await goRoom(app, "Arbete");
      await expect(h2(app, "Minne och kontroll")).toHaveCount(0);
      await expect(back(app)).toHaveCount(0);
      await expectCurrentRoom(app, "Arbete");
      expect(failures).toEqual([]);
    });

    test(`a token without journal access: a calm line, no retry (${suffix})`, async ({
      page,
    }) => {
      const forbidden = {
        isError: true,
        structuredContent: { code: "forbidden", message: "Forbidden." },
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: { items: [], filters: {}, next_cursor: null },
        replies: { get_journal_day: forbidden, get_journal_entry: forbidden },
      });
      await goRoom(app, "Dagbok");
      await expect(
        app.getByText("Sidekick-anslutningen har inte tillgång till Dagbok."),
      ).toBeVisible();
      await expect(
        app.getByRole("button", { name: "Försök igen" }),
      ).toHaveCount(0);
      // The strip still shows every room.
      await expectRoomNames(app, ["Arbete", "Dagbok", "Kontakter", "Inköp"]);
      expect(failures).toEqual([]);
    });

    test(`closing fullscreen shows the original card; reopening starts where the card pointed (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_entry",
        result: opening.journalEntry,
      });
      await app
        .getByRole("button", { name: "Anna Andersson", exact: true })
        .click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await setHostContext(page, { displayMode: "inline" });
      await expect(strip(app)).toHaveCount(0);
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await setHostContext(page, { displayMode: "fullscreen" });
      await expect(strip(app)).toBeVisible();
      // The card's own target (the entry), not the Contact the user left it on.
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await expect(h2(app, "Anna Andersson")).toHaveCount(0);
      await expect(back(app)).toHaveCount(1);
      expect(failures).toEqual([]);
    });

    test(`Open the board opens the board, not the room visited last (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_board",
        result: opening.workBoard,
      });
      await chooseView(app, "Status", width);
      await goRoom(app, "Kontakter");
      await app
        .getByRole("button", { name: "Anna Andersson", exact: true })
        .click();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await setHostContext(page, { displayMode: "inline" });
      await expect(strip(app)).toHaveCount(0);
      await app.getByRole("button", { name: "Öppna status" }).click();
      await expect(strip(app)).toBeVisible();
      await expectCurrentRoom(app, "Arbete");
      await expect(h2(app, "Anna Andersson")).toHaveCount(0);
      await expect(back(app)).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`a card that opens on a task: the agenda is its root, Back leads there (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_task",
        result: { task },
        replies: { get_task: { structuredContent: { task } } },
      });
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await expect(app.locator(".work-back")).toHaveCount(0);
      await back(app).click();
      await expect(back(app)).toHaveCount(0);
      await expect(
        app.getByRole("button", { name: "Ring Anna om offerten", exact: true }),
      ).toBeVisible();
      // And a press on the active room is the root as well.
      await openTask(app).click();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await goRoom(app, "Arbete");
      await expect(back(app)).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`a card that opens on a contact: the list is its root (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_contact_context",
        result: {
          contact: anna,
          projects: { items: [], next_cursor: null },
          tasks: { items: [], next_cursor: null },
        },
      });
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await back(app).click();
      await expect(back(app)).toHaveCount(0);
      await expect(
        app.getByRole("button", { name: "Bo Berg", exact: true }),
      ).toBeVisible();
      expect(failures).toEqual([]);
    });
  }
}
