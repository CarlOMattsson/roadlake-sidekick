import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  simulatedHostState,
  waitForAppInitialized,
  type AppLocale,
} from "./mcp-host-fixture";
import {
  emptyPage,
  groupDecided,
  inboxPage,
  sid,
  suggestionReplies,
} from "./suggestions-fixtures";

// The Start room's suggestion inbox on the SIMULATED host (mcp-host-fixture.ts): every tool answer is a fixture, no
// backend, no database, no network. This is not a run in a real Claude or Android host. With SUGGESTION_SHOTS=<dir>
// each test also writes its screenshots there.

type Open = {
  width: number;
  height?: number;
  theme?: "light" | "dark";
  locale?: AppLocale;
  displayMode?: "inline" | "fullscreen";
  tool?: string;
  result?: unknown;
  replies?: Record<string, unknown>;
};

async function open(page: Page, options: Open) {
  const theme = options.theme ?? "light";
  const locale = options.locale ?? "sv";
  await page.clock.setFixedTime(new Date("2026-11-23T08:00:00Z"));
  await page.emulateMedia({ colorScheme: theme });
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", locale),
    width: options.width,
    height: options.height ?? 844,
    hostContext: {
      locale,
      theme,
      displayMode: options.displayMode ?? "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: options.tool ?? "list_suggestions" } },
      platform: options.width >= 1024 ? "desktop" : "mobile",
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: { ...suggestionReplies, ...options.replies },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, options.result ?? inboxPage);
  await settled(opened.app);
  return opened;
}

async function shot(page: Page, name: string) {
  const out = process.env.SUGGESTION_SHOTS;
  if (!out) return;
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
}

const card = (app: FrameLocator, title: string) =>
  app.locator("article.sk-decision", {
    has: app.getByRole("heading", { name: title }),
  });

test("the inbox groups the safe ones, three per confirmation, and approves them with Ångra", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await open(page, {
    width: 390,
    replies: { decide_suggestions: groupDecided },
  });
  await expect(
    app.getByRole("heading", { level: 2, name: "Förslag" }),
  ).toBeVisible();
  await expect(app.getByText("Från Morgonmejl", { exact: true })).toBeVisible();
  await expect(app.getByText("Säkra förslag (4)")).toBeVisible();
  // Only the first three form the batch; the fourth waits for the next confirmation.
  await expect(
    app.getByRole("button", { name: /Skapa uppgift: Ring Karin/ }),
  ).toBeVisible();
  await expect(app.getByText("Beställ kakel till badrummet")).toHaveCount(0);
  await expect(
    app.getByText("1 till efter de här, högst 3 åt gången"),
  ).toBeVisible();
  await expect(app.getByText("Att granska (3)")).toBeVisible();
  await shot(page, "inbox-390-light-sv");

  await app.getByRole("button", { name: "Godkänn 3" }).click();
  await expect(
    app.getByRole("status").filter({ hasText: "Godkända: 3 förslag" }),
  ).toBeVisible();
  await expect(app.getByRole("button", { name: "Ångra" })).toBeVisible();
  const { calls } = await simulatedHostState(page);
  // A part of the server's group (the first three of four) is decided card by card, never with the group's digest.
  const decide = calls.find((call) => call.name === "decide_suggestions");
  expect(decide?.arguments.items).toEqual(
    [1, 2, 3].map((n) => ({
      suggestion_id: sid(n),
      expected_version: 1,
      decision: "approve",
    })),
  );
  expect(calls.some((call) => call.name === "approve_suggestion_group")).toBe(
    false,
  );
  await shot(page, "inbox-390-group-approved");

  await app.getByRole("button", { name: "Ångra" }).click();
  await expect
    .poll(
      async () =>
        (await simulatedHostState(page)).calls.filter(
          (call) => call.name === "undo_suggestion",
        ).length,
    )
    .toBe(3);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("a suspicious card has no Godkänn; Granska opens its detail with the quote and Godkänn ändå asks first", async ({
  page,
}) => {
  const { app } = await open(page, { width: 390 });
  const suspicious = card(app, "Skapa uppgift: Betala ny faktura");
  await expect(suspicious.getByText("Misstänkt förslag")).toBeVisible();
  await expect(
    suspicious.getByRole("button", { name: "Godkänn", exact: true }),
  ).toHaveCount(0);
  await suspicious.getByRole("button", { name: "Granska" }).click();
  await expect(
    app.getByText("Ur mejlet, inte skrivet av Sidekick"),
  ).toBeVisible();
  // A web address in the quote is its domain name in plain text, never a link.
  await expect(app.getByText(/pay\.example\.net/)).toBeVisible();
  await expect(app.locator("blockquote a")).toHaveCount(0);
  await expect(app.getByText(/Inte bland de säkra:/)).toBeVisible();
  await shot(page, "detail-390-suspicious");
  await app.getByRole("button", { name: "Godkänn ändå" }).click();
  await expect(app.getByText("Godkänna ett misstänkt förslag?")).toBeVisible();
  await expect(app.getByRole("button", { name: "Avbryt" })).toBeFocused();
});

test("one card approves with Ångra in the bar and holds its place as its receipt", async ({
  page,
}) => {
  const { app } = await open(page, { width: 390 });
  const erik = card(app, "Skapa uppgift: Svara Erik om hyresgästen");
  const before = await erik.boundingBox();
  await erik.getByRole("button", { name: "Godkänn", exact: true }).click();
  await expect(
    app.getByText("Tillagd: Svara Erik om hyresgästen"),
  ).toBeVisible();
  const held = app.locator("article.sk-decision--decided");
  const after = await held.boundingBox();
  expect(Math.round(after?.height ?? 0)).toBe(Math.round(before?.height ?? -1));
  const decide = (await simulatedHostState(page)).calls.find(
    (call) => call.name === "decide_suggestions",
  );
  expect(decide?.arguments.items).toEqual([
    { suggestion_id: sid(7), expected_version: 1, decision: "approve" },
  ]);
  await shot(page, "inbox-390-card-approved");
  await app.getByRole("button", { name: "Ångra" }).click();
  await expect
    .poll(
      async () =>
        (await simulatedHostState(page)).calls.find(
          (call) => call.name === "undo_suggestion",
        )?.arguments,
    )
    .toMatchObject({ suggestion_id: sid(7), expected_version: 2 });
});

for (const theme of ["light", "dark"] as const)
  test(`a wide frame opens a card beside the inbox (${theme})`, async ({
    page,
  }) => {
    const { app } = await open(page, { width: 1440, height: 900, theme });
    await shot(page, `inbox-1440-${theme}`);
    await app.getByRole("button", { name: "Skapa kontakt: Lena Holm" }).click();
    await expect(
      app.locator("[data-pane='detail']").getByText("Kontrollen var osäker"),
    ).toBeVisible();
    await expect(
      app
        .locator("[data-pane='detail']")
        .getByText("Ur mejlet, inte skrivet av Sidekick"),
    ).toBeVisible();
    await expect(
      app.locator(`[data-sk-record="start:suggestion:${sid(5)}"]`),
    ).toHaveAttribute("aria-current", "true");
    await shot(page, `detail-1440-${theme}`);
  });

for (const width of [740, 390, 360] as const)
  test(`the inline card holds the group within a phone's card height at ${width}`, async ({
    page,
  }) => {
    const { app } = await open(page, { width, displayMode: "inline" });
    const inline = app.locator(".start-inline .sk-card").first();
    await expect(inline.getByText("4 säkra förslag")).toBeVisible();
    await expect(
      app.getByRole("button", { name: /Öppna Förslag/ }),
    ).toBeVisible();
    const box = await inline.boundingBox();
    expect(box?.height ?? 999).toBeLessThanOrEqual(340);
    await shot(page, `inline-${width}-light`);
  });

test("an empty inbox says so, in English too", async ({ page }) => {
  const { app } = await open(page, {
    width: 390,
    locale: "en",
    theme: "dark",
    result: emptyPage,
    replies: { list_suggestions: { structuredContent: emptyPage } },
  });
  await expect(
    app.getByRole("heading", { level: 2, name: "Suggestions" }),
  ).toBeVisible();
  await expect(app.getByText("No suggestions right now.")).toBeVisible();
  await shot(page, "empty-390-dark-en");
});

test("the English inbox uses the app's words for the effect", async ({
  page,
}) => {
  const { app } = await open(page, { width: 360, locale: "en" });
  await expect(app.getByText("Safe suggestions (4)")).toBeVisible();
  await expect(
    app.getByRole("button", {
      name: /Create task: Call|Create task: Ring Karin/,
    }),
  ).toBeVisible();
  await expect(app.getByRole("button", { name: "Approve 3" })).toBeVisible();
  await shot(page, "inbox-360-light-en");
});

test("a failed read offers Försök igen and reads again", async ({ page }) => {
  const { app } = await open(page, {
    width: 390,
    tool: "get_work_agenda",
    result: { items: [], filters: {} },
    replies: {
      list_suggestions: {
        __sequence: [
          { isError: true, content: [{ type: "text", text: "boom" }] },
          { structuredContent: inboxPage },
        ],
      },
    },
  });
  await app
    .getByRole("navigation", { name: "Rum" })
    .getByRole("button", { name: /Start/ })
    .click();
  await expect(app.getByText("Förslagen kunde inte hämtas")).toBeVisible();
  await shot(page, "error-390");
  await app.getByRole("button", { name: "Försök igen" }).click();
  await expect(app.getByText("Säkra förslag (4)")).toBeVisible();
});
