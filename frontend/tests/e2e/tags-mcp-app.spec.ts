import { expect, test, type Page } from "@playwright/test";
import {
  bigAgenda,
  bigBoard,
  bigContactContext,
  bigContactList,
  bigJournalDay,
  FIXTURE_NOW,
  fullTask,
  journalReplies,
  projectRecord,
  workReplies,
} from "./one-screen-fixtures";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  settled,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// Tags on Contacts and Journal entries in a real Chromium on the simulated host (mcp-host-fixture.ts), not a real
// Claude or Android host: every tool answer is a fixture and the network is closed. The filter reads with every
// chosen tag (tag_match "all"), a tag change is one update_contact of the whole set, and every tag control is a
// 44 px target.

const TAP = 44;
const replies = {
  ...workReplies,
  ...journalReplies,
  list_journal_entries: {
    structuredContent: { entries: bigJournalDay.entries, next_cursor: null },
  },
  update_contact: {
    structuredContent: {
      contact: {
        ...bigContactContext.contact,
        tags: [...bigContactContext.contact.tags, "familj"],
        version: 3,
      },
    },
  },
  update_task: {
    structuredContent: {
      task: { ...fullTask, tags: [...fullTask.tags, "viktig"], version: 4 },
    },
  },
  update_project: {
    structuredContent: {
      project: { ...projectRecord, tags: [], version: 3 },
    },
  },
};

/** The fullscreen room on the simulated host, at a phone's size unless `width` says otherwise. */
async function openWork(
  page: Page,
  result: unknown,
  options: {
    locale?: "sv" | "en";
    width?: number;
    theme?: "light" | "dark";
  } = {},
) {
  const locale = options.locale ?? "sv";
  await page.clock.setFixedTime(FIXTURE_NOW);
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", locale),
    width: options.width ?? 375,
    height: 812,
    hostContext: {
      locale,
      theme: options.theme ?? "light",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
    },
    replies,
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, result);
  await settled(opened.app);
  return opened;
}

for (const [view, tool, result] of [
  ["Agenda", "get_work_agenda", bigAgenda],
  ["Status", "get_work_board", bigBoard],
] as const)
  test(`${view}: the tag filter reads with every chosen tag, and a tagged row keeps one meta line`, async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await openWork(page, result);
    const filter = app.getByRole("group", { name: "Filtrera på tagg" });
    await expect(filter).toBeVisible();
    for (const chip of await filter.getByRole("button").all()) {
      const size = await effectiveTargetSize(chip);
      expect(size?.height).toBeGreaterThanOrEqual(TAP);
      expect(size?.width).toBeGreaterThanOrEqual(TAP);
    }
    // Two pills and "+1" on the meta line, drawn to its height: a tagged row is as tall as an untagged one.
    const metas = app.locator(
      ".work-agenda-body > .work-card-meta:has(.sk-tags), li.work-card > .work-card-meta:has(.sk-tags)",
    );
    expect(await metas.count()).toBeGreaterThan(0);
    for (const box of await metas.evaluateAll((all) =>
      all.map((el) => el.getBoundingClientRect().height),
    ))
      expect(box).toBeLessThanOrEqual(18);
    await expect(app.locator(".work-card-meta .sk-tags-sr").first()).toHaveText(
      /^Taggar: /,
    );
    await filter.getByRole("button", { name: "viktig" }).click();
    await expect(
      filter.getByRole("button", { name: "viktig" }),
    ).toHaveAttribute("aria-pressed", "true");
    await filter.getByRole("button", { name: "kund" }).click();
    await settled(app);
    const reads = (await simulatedHostState(page)).calls.filter(
      (call) => call.name === tool,
    );
    expect(reads.at(-1)?.arguments).toMatchObject({
      tags: ["viktig", "kund"],
      tag_match: "all",
    });
    await filter.getByRole("button", { name: "Rensa" }).click();
    await settled(app);
    const cleared = (await simulatedHostState(page)).calls.filter(
      (call) => call.name === tool,
    );
    expect(cleared.at(-1)?.arguments).not.toHaveProperty("tags");
    expect(networkRequests()).toBe(0);
    expect(failures).toEqual([]);
  });

test("Journal day: a row's tags are read whole at a phone's width", async ({
  page,
}) => {
  const { app, failures } = await openWork(page, bigJournalDay, {
    width: 375,
  });
  const chips = app.locator(".journal-entry-row .sk-tag:not(.sk-tag--more)");
  expect(await chips.count()).toBeGreaterThan(0);
  // No pill is cut: its text fits its box (no ellipsis) and it stays inside the row.
  for (const chip of await chips.all()) {
    const fits = await chip.evaluate(
      (el) =>
        el.scrollWidth <= el.clientWidth &&
        el.getBoundingClientRect().right <=
          (el.closest(".journal-entry-card")?.getBoundingClientRect().right ??
            0) +
            1,
    );
    expect(fits).toBe(true);
  }
  expect(failures).toEqual([]);
});

test("Task: a tag added from the suggestions is one update_task of the whole set", async ({
  page,
}) => {
  const { app, failures } = await openWork(
    page,
    { task: fullTask },
    {
      locale: "en",
      theme: "dark",
    },
  );
  const open = app.getByRole("button", {
    name: `Edit tags for ${fullTask.title}`,
  });
  expect((await effectiveTargetSize(open))?.height).toBeGreaterThanOrEqual(TAP);
  await open.click();
  await expect(app.getByRole("textbox", { name: "New tag" })).toBeFocused();
  await app.getByRole("button", { name: "Add tag viktig" }).click();
  await expect(
    app.getByRole("button", { name: "Remove tag viktig" }),
  ).toBeVisible();
  const write = (await simulatedHostState(page)).calls.find(
    (call) => call.name === "update_task",
  );
  expect(write?.arguments).toMatchObject({
    task_id: fullTask.id,
    changes: { tags: ["kund", "byggprojekt-göteborg", "viktig"] },
  });
  // The editor stays open with the focus in it: a tag write does not move it to the title.
  await expect(app.getByRole("textbox", { name: "New tag" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
  expect(failures).toEqual([]);
});

test("Project: removing its tag is one update_project, and its Tasks show their tags", async ({
  page,
}) => {
  const { app, failures } = await openWork(page, { project: projectRecord });
  await expect(
    app.locator(".work-list .work-card-meta .sk-tags").first(),
  ).toBeVisible();
  await app
    .getByRole("button", { name: `Ändra taggar för ${projectRecord.title}` })
    .click();
  await app.getByRole("button", { name: "Ta bort taggen styrelse" }).click();
  await expect(app.getByRole("textbox", { name: "Ny tagg" })).toBeFocused();
  const write = (await simulatedHostState(page)).calls.find(
    (call) => call.name === "update_project",
  );
  expect(write?.arguments).toMatchObject({
    project_id: projectRecord.id,
    changes: { tags: [] },
  });
  expect(failures).toEqual([]);
});

for (const width of [320, 412])
  test(`Contacts: the tag filter reads with every chosen tag and its chips are ${TAP} px targets (${width})`, async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await openSimulatedApp(page, {
      resource: readBuiltApp("sidekick", "sv"),
      width,
      height: 800,
      hostContext: {
        locale: "sv",
        theme: "dark",
        displayMode: "fullscreen",
        availableDisplayModes: ["inline", "fullscreen"],
      },
      replies,
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, bigContactList);
    const filter = app.getByRole("group", { name: "Filtrera på tagg" });
    await expect(filter).toBeVisible();
    for (const chip of await filter.getByRole("button").all()) {
      const size = await effectiveTargetSize(chip);
      expect(size?.height).toBeGreaterThanOrEqual(TAP);
      expect(size?.width).toBeGreaterThanOrEqual(TAP);
    }
    await filter.getByRole("button", { name: "viktig" }).click();
    await filter.getByRole("button", { name: "kund" }).click();
    await expect(filter.getByRole("button", { name: "Rensa" })).toBeVisible();
    await settled(app);
    const reads = (await simulatedHostState(page)).calls.filter(
      (call) => call.name === "list_contacts",
    );
    expect(reads.at(-1)?.arguments).toMatchObject({
      tags: ["viktig", "kund"],
      tag_match: "all",
    });
    // A tagged row keeps the meta line to one line: two pills and "+1", never a second line of tags.
    const row = app
      .getByRole("button", { name: /^Cecilia Carlsson Taggar:/ })
      .first();
    await expect(row).toContainText("+1");
    expect((await row.boundingBox())?.height).toBeLessThanOrEqual(60);
    expect(networkRequests()).toBe(0);
    expect(failures).toEqual([]);
  });

test("Contact: a tag added from the suggestions is one update_contact of the whole set", async ({
  page,
}) => {
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", "en"),
    width: 375,
    height: 812,
    hostContext: {
      locale: "en",
      theme: "light",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
    },
    replies,
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, bigContactContext);
  await app
    .getByRole("button", { name: "Edit tags for Anna Andersson" })
    .click();
  await expect(app.getByRole("textbox", { name: "New tag" })).toBeFocused();
  for (const remove of await app
    .getByRole("button", { name: /^Remove tag / })
    .all()) {
    const size = await effectiveTargetSize(remove);
    expect(size?.height).toBeGreaterThanOrEqual(TAP);
  }
  await app.getByRole("button", { name: "Add tag familj" }).click();
  await expect(
    app.getByRole("button", { name: "Remove tag familj" }),
  ).toBeVisible();
  const write = (await simulatedHostState(page)).calls.find(
    (call) => call.name === "update_contact",
  );
  expect(write?.arguments).toMatchObject({
    changes: { tags: ["kund", "viktig", "byggprojekt-göteborg", "familj"] },
    expected_version: 2,
  });
  await page.keyboard.press("Escape");
  await expect(
    app.getByRole("button", { name: "Edit tags for Anna Andersson" }),
  ).toBeFocused();
  expect(failures).toEqual([]);
});

test("Journal: choosing a tag lists the tagged entries across days", async ({
  page,
}) => {
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", "sv"),
    width: 375,
    height: 812,
    hostContext: {
      locale: "sv",
      theme: "light",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
    },
    replies,
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, bigJournalDay);
  const filter = app.getByRole("group", { name: "Filtrera på tagg" });
  await filter.getByRole("button", { name: "viktig" }).click();
  await settled(app);
  const read = (await simulatedHostState(page)).calls.filter(
    (call) =>
      call.name === "list_journal_entries" &&
      Array.isArray(call.arguments.tags),
  );
  expect(read.at(-1)?.arguments).toMatchObject({
    tags: ["viktig"],
    tag_match: "all",
  });
  await filter.getByRole("button", { name: "Rensa" }).click();
  await expect(filter.getByRole("button", { name: "viktig" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(failures).toEqual([]);
});
