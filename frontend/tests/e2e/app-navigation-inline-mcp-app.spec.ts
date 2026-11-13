import { test, expect } from "@playwright/test";
import { ids, ok, opening, task, workItem } from "./sidekick-domain-fixtures";
import { setHostContext, setHostReply } from "./mcp-host-fixture";
import {
  widths,
  themes,
  openSidekick,
  strip,
  back,
  h2,
  goRoom,
  doneTask,
  callNames,
} from "./app-navigation-fixtures";

// The inline cards and the full view: what a write in the full view shows on the card, and the entry card's links.
// SIMULATED host; see app-navigation-mcp-app.spec.ts for the rule they share (one visible Back).

for (const width of widths) {
  for (const theme of themes) {
    const suffix = `${width} px, ${theme}`;

    test(`the inline task card shows the status written in the full view (${suffix})`, async ({
      page,
    }) => {
      const completed = {
        ...task,
        status: "completed",
        completed_at: "2026-10-24T13:00:00Z",
        version: 2,
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_task",
        result: { task },
        displayMode: "inline",
        replies: {
          get_task: {
            __sequence: [
              { structuredContent: { task } },
              { structuredContent: { task: completed } },
            ],
          },
          update_task: { structuredContent: { task: completed } },
        },
      });
      await expect(app.getByText("Att göra").first()).toBeVisible();
      await app.getByRole("button", { name: /^Öppna uppgiften/ }).click();
      // The host answers the request: it puts the app in fullscreen.
      await setHostContext(page, { displayMode: "fullscreen" });
      await expect(strip(app)).toBeVisible();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      await app.getByRole("button", { name: "Markera klar" }).click();
      await expect(app.getByText("Sparat", { exact: true })).toBeVisible();
      await setHostContext(page, { displayMode: "inline" });
      await expect(strip(app)).toHaveCount(0);
      // The card reads the task again: it says Klar, and the Done button is gone.
      await expect(app.getByText("Klar").first()).toBeVisible();
      await expect(app.getByText("Att göra")).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`the inline agenda card shows what was done in the full view (${suffix})`, async ({
      page,
    }) => {
      const agenda = {
        items: [workItem(task)],
        filters: {},
        next_cursor: null,
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: agenda,
        displayMode: "inline",
        replies: {
          get_work_agenda: ok(agenda),
          update_task: ok({ task: doneTask }),
        },
      });
      await expect(
        app.getByText(/Ring Anna om offerten/).first(),
      ).toBeVisible();
      await setHostContext(page, { displayMode: "fullscreen" });
      await expect(strip(app)).toBeVisible();
      await setHostReply(
        page,
        "get_work_agenda",
        ok({ items: [], filters: {}, next_cursor: null }),
      );
      await app
        .getByRole("button", { name: /Markera Ring Anna om offerten/ })
        .first()
        .click();
      await expect
        .poll(async () => (await callNames(page)).includes("update_task"))
        .toBe(true);
      await setHostContext(page, { displayMode: "inline" });
      await expect(strip(app)).toHaveCount(0);
      // The card reads the agenda again: the finished task is not on it.
      await expect(app.getByText(/Ring Anna om offerten/)).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`a contact name on the inline entry card opens the contact in the full view (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "update_journal_entry",
        result: { entry: opening.journalEntry.entry },
        displayMode: "inline",
      });
      await expect(strip(app)).toHaveCount(0);
      const name = app.getByRole("button", {
        name: "Anna Andersson",
        exact: true,
      });
      await expect(name).toBeVisible();
      // Two actions at most: Open, and the chips. The cross removes with an Undo line.
      await name.click();
      await expect(strip(app)).toBeVisible();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await expect(back(app)).toHaveCount(1);
      await back(app).click();
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      expect(failures).toEqual([]);
      expect(ids.anna).toBeTruthy();
    });

    test(`the inline entry card names its links as text without a cross; the entry view's cross asks before it removes (${suffix})`, async ({
      page,
    }) => {
      // No × on the inline card, "Kopplad till Anna Andersson" as text; unlink in fullscreen.
      const card = await openSidekick(page, {
        width,
        theme,
        tool: "update_journal_entry",
        result: { entry: opening.journalEntry.entry },
        displayMode: "inline",
      });
      // Inline card: one meta line, "Sammanfattad av Claude · Kopplad till …", and no cross.
      await expect(card.app.locator(".journal-card-links")).toHaveText(
        "Sammanfattad av Claude · Kopplad till Anna Andersson · 1 uppgift",
      );
      await expect(
        card.app.getByRole("button", { name: /^Ta bort kopplingen/ }),
      ).toHaveCount(0);
      expect(card.failures).toEqual([]);

      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_entry",
        result: opening.journalEntry,
      });
      // The cross is part of changing the entry: none in the view, one per chip after "Ändra anteckningen".
      await expect(
        app.getByRole("button", { name: /^Ta bort kopplingen/ }),
      ).toHaveCount(0);
      await app.getByRole("button", { name: "Ändra anteckningen" }).click();
      await app
        .getByRole("button", { name: "Ta bort kopplingen till Anna Andersson" })
        .click();
      await expect(
        app.getByText("Ta bort kopplingen till Anna Andersson?"),
      ).toBeVisible();
      await expect(
        app.locator(".journal-link-ask").getByRole("button"),
      ).toHaveText(["Ta bort", "Avbryt"]);
      // Nothing was written by the first press.
      expect(await callNames(page)).not.toContain("update_journal_entry");
      await app
        .locator(".journal-link-ask")
        .getByRole("button", { name: "Avbryt" })
        .click();
      await expect(
        app.getByRole("button", { name: "Anna Andersson", exact: true }),
      ).toBeVisible();
      expect(await callNames(page)).not.toContain("update_journal_entry");
      expect(failures).toEqual([]);
    });

    test(`the card's own entry counts in a loop: entry to Anna to the same entry is one Back from the day (${suffix})`, async ({
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
      await app
        .getByRole("button", { name: /Lunch med Anna/ })
        .first()
        .click();
      await expect(h2(app, "Lunch med Anna")).toBeVisible();
      await back(app).click();
      await expect(back(app)).toHaveCount(0);
      expect(failures).toEqual([]);
    });

    test(`every room starts at the same left edge as the strip (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: { items: [], filters: {}, next_cursor: null },
      });
      const edges: Record<string, number> = {};
      for (const [name, id] of [
        ["Arbete", "work"],
        ["Dagbok", "journal"],
        ["Kontakter", "contacts"],
        ["Inköp", "shopping"],
      ] as const) {
        await goRoom(app, name);
        await expect(
          app
            .locator(`[data-room="${id}"] [data-layer-top="true"] > *`)
            .first(),
        ).toBeVisible();
        edges[id] = await app
          .locator(`[data-room="${id}"] [data-layer-top="true"] > *`)
          .first()
          .evaluate((el) => el.getBoundingClientRect().left);
      }
      const bar = await app
        .locator(".sk-rooms")
        .evaluate((el) => el.getBoundingClientRect().left);
      for (const id of Object.keys(edges))
        expect(Math.abs((edges[id] ?? 0) - bar), id).toBeLessThanOrEqual(1);
      expect(failures).toEqual([]);
    });
  }
}
