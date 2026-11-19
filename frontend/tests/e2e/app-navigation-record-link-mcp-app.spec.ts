import { test, expect } from "@playwright/test";
import {
  anna,
  contactContext,
  entry,
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

    test(`a row of the inline contact list opens that contact in the full view (${suffix})`, async ({
      page,
    }) => {
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "list_contacts",
        result: opening.contactList,
        displayMode: "inline",
      });
      await expect(strip(app)).toHaveCount(0);
      await app
        .getByRole("button", { name: /Bo Berg/ })
        .first()
        .click();
      await expect(strip(app)).toBeVisible();
      await expect(h2(app, "Bo Berg")).toBeVisible();
      expect((await simulatedHostState(page)).displayModeRequests).toEqual([
        "fullscreen",
      ]);
      expect(failures).toEqual([]);
    });

    test(`the contact a waiting row names opens in the full view from the inline card (${suffix})`, async ({
      page,
    }) => {
      const waiting = {
        items: [
          {
            ...workItem(task),
            waiting: true,
            waiting_since: "2026-10-18T09:00:00+02:00",
            waiting_on_contact_id: ids.anna,
            waiting_on_contact_name: "Anna Andersson",
          },
        ],
        filters: { waiting: "waiting" },
        next_cursor: null,
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_work_agenda",
        result: waiting,
        displayMode: "inline",
        replies: { get_work_agenda: ok(waiting) },
      });
      await expect(strip(app)).toHaveCount(0);
      await app.getByRole("button", { name: "Anna Andersson" }).click();
      await expect(strip(app)).toBeVisible();
      await expect(h2(app, "Anna Andersson")).toBeVisible();
      expect((await simulatedHostState(page)).displayModeRequests).toEqual([
        "fullscreen",
      ]);
      expect(failures).toEqual([]);
    });

    test(`a project chip under Linked opens the project (${suffix})`, async ({
      page,
    }) => {
      const project = {
        id: "019f0000-0000-7000-8000-0000000000b1",
        title: "Flytten",
        description: null,
        status: "active",
        start_date: null,
        target_date: null,
        created_at: "2026-10-24T12:00:00Z",
        updated_at: "2026-10-24T12:00:00Z",
        version: 1,
      };
      const linked = {
        ...entry,
        project_ids: [project.id],
        links: [
          ...entry.links,
          { kind: "project", id: project.id, label: project.title },
        ],
      };
      const { app, failures } = await openSidekick(page, {
        width,
        theme,
        tool: "get_journal_entry",
        result: { entry: linked },
        replies: {
          get_journal_entry: ok({ entry: linked }),
          get_project: ok({ project }),
          list_tasks: ok({ tasks: [], next_cursor: null }),
        },
      });
      await app.getByRole("button", { name: "Flytten" }).click();
      await expect(h2(app, "Flytten")).toBeVisible();
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
