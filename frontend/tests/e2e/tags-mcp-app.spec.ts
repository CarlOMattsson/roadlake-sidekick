import { expect, test } from "@playwright/test";
import {
  bigContactContext,
  bigContactList,
  bigJournalDay,
  journalReplies,
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
};

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
    await expect(
      filter.getByRole("button", { name: "Rensa taggfiltret" }),
    ).toBeVisible();
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
  await filter.getByRole("button", { name: "Rensa taggfiltret" }).click();
  await expect(filter.getByRole("button", { name: "viktig" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(failures).toEqual([]);
});
