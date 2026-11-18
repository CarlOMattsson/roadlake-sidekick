import { test, expect } from "@playwright/test";
import {
  anna,
  contactContext,
  ids,
  ok,
  opening,
  task,
  workItem,
} from "./sidekick-domain-fixtures";
import { setHostContext, simulatedHostState } from "./mcp-host-fixture";
import {
  widths,
  themes,
  openSidekick,
  strip,
  back,
  h2,
} from "./app-navigation-fixtures";

// A row of an inline list card opens its own record in the full view, and a link in a room goes through the host.
// SIMULATED host (mcp-host-fixture.ts), not a real Claude or Android host. The host here grants the display-mode
// request and, as some hosts do, reports nothing until the test has the host report fullscreen.

const agenda = { items: [workItem(task)], filters: {}, next_cursor: null };

for (const width of widths) {
  for (const theme of themes) {
    const suffix = `${width} px, ${theme}`;

    test(`a row of the inline agenda card opens that task in the full view (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: agenda,
        displayMode: "inline",
        replies: { get_work_agenda: ok(agenda), get_task: ok({ task }) },
      });
      await expect(strip(app)).toHaveCount(0);
      await app
        .getByRole("button", { name: /Ring Anna om offerten/ })
        .first()
        .click();
      await expect(strip(app)).toBeVisible();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      // The agenda is the one step back, not the start of a new walk.
      await expect(back(app)).toHaveCount(1);
      expect((await simulatedHostState(page)).displayModeRequests).toEqual([
        "fullscreen",
      ]);
      // The host now reports fullscreen: the task stays open.
      await setHostContext(page, { displayMode: "fullscreen" });
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      expect(failures).toEqual([]);
    });

    test(`a row of the inline status card opens that task in the full view (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_board",
        result: opening.workBoard,
        displayMode: "inline",
        replies: { get_task: ok({ task }) },
      });
      await expect(strip(app)).toHaveCount(0);
      await app
        .getByRole("button", { name: /Ring Anna om offerten/ })
        .first()
        .click();
      await expect(strip(app)).toBeVisible();
      await expect(h2(app, "Ring Anna om offerten")).toBeVisible();
      expect(failures).toEqual([]);
    });

    test(`the ways to reach a contact open through the host and never navigate the app (${suffix})`, async ({
      page,
    }) => {
      const slack = "https://acme.slack.com/team/U123ABC";
      const context = contactContext(anna).structuredContent as {
        contact: object;
      };
      const withWays = {
        ...context,
        contact: {
          ...context.contact,
          email: "anna@example.com",
          phone: "+46 70 123 45 67",
          slack,
        },
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_contact_context",
        result: withWays,
        capabilities: { serverTools: {}, message: {}, openLinks: {} },
        replies: {
          get_contact_context: {
            __byArgument: {
              key: "contact_id",
              answers: { [ids.anna]: ok(withWays) },
            },
          },
        },
      });
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      await app.getByRole("button", { name: /Kontaktvägar/ }).click();
      for (const link of [
        "anna@example.com",
        "+46 70 123 45 67",
        "acme.slack.com",
      ])
        await app.getByRole("link", { name: link }).click();
      await expect
        .poll(async () => (await simulatedHostState(page)).openLinks)
        .toEqual(["mailto:anna@example.com", "tel:+46701234567", slack]);
      // The frame is still the app: no link took it over.
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      expect(page.frames().map((frame) => frame.url())).not.toContain(slack);
      expect(failures).toEqual([]);
    });
  }
}
