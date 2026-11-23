import {
  expect,
  test,
  type FrameLocator,
  type Locator,
  type Page,
} from "@playwright/test";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  settled,
  simulatedHostState,
  waitForAppInitialized,
  type AppLocale,
} from "./mcp-host-fixture";
import { automationReplies } from "./automations-fixtures";
import { domainReplies, opening } from "./sidekick-domain-fixtures";
import { homeIds, homeReplies, fullStart } from "./start-home-fixtures";
import { suggestionReplies } from "./suggestions-fixtures";

// The Start room's home view on the SIMULATED host (mcp-host-fixture.ts): every tool answer is a fixture, no backend,
// no database, no network. This is not a run in a real Claude or Android host. The app opens on a Work result and the
// person goes to Start from the room strip, as in a fullscreen card. The simulated host does not answer ui/message, so
// "Starta" is proven in the view tests (start-home.test.tsx), not here. With START_HOME_SHOTS=<dir> each test also
// writes its screenshots there.

type Open = {
  width: number;
  height?: number;
  theme?: "light" | "dark";
  locale?: AppLocale;
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
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: "get_work_board" } },
      platform: options.width >= 1024 ? "desktop" : "mobile",
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: {
      ...domainReplies(),
      ...suggestionReplies,
      ...automationReplies,
      ...homeReplies,
      ...options.replies,
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, opening.workBoard);
  await settled(opened.app);
  await goStart(opened.app, locale);
  return opened;
}

/** The strip's Start ("Home" in English): its cell, or the picker's row where the names do not fit one line. */
async function goStart(app: FrameLocator, locale: AppLocale) {
  const strip = app.getByRole("navigation", {
    name: locale === "sv" ? "Rum" : "Rooms",
  });
  await expect(strip).toBeVisible();
  const room = locale === "sv" ? "Start" : "Home";
  if ((await strip.locator(".sk-rooms__tabs[data-narrow]").count()) > 0) {
    await strip.locator(".sk-pick").click();
    await app.getByRole("menuitemradio", { name: room, exact: true }).click();
  } else await strip.getByRole("button", { name: room }).first().click();
  await expect(app.locator(".start-home .start-inbox-title")).toBeVisible();
  await settled(app);
}

async function shot(page: Page, name: string) {
  const out = process.env.START_HOME_SHOTS;
  if (!out) return;
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
}

const home = (app: FrameLocator) => app.locator(".start-home");

/** Every control on the page is a 44 target, and nothing reaches past the frame. */
async function expectFits(app: FrameLocator, scope: Locator) {
  const controls = scope.locator("button:visible");
  const count = await controls.count();
  expect(count).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) {
    const size = await effectiveTargetSize(controls.nth(index));
    expect(size?.height ?? 0, `control ${index}`).toBeGreaterThanOrEqual(44);
  }
  const measures = await scope.evaluate((element) => {
    const root = element.ownerDocument.documentElement;
    const widest = Math.max(
      ...[...element.querySelectorAll("*")].map(
        (child) => child.getBoundingClientRect().right,
      ),
    );
    return {
      overflow: root.scrollWidth - root.clientWidth,
      widest,
      frame: root.clientWidth,
    };
  });
  expect(measures.overflow).toBeLessThanOrEqual(0);
  expect(measures.widest).toBeLessThanOrEqual(measures.frame);
  void app;
}

const calls = async (page: Page, name: string) =>
  (await simulatedHostState(page)).calls.filter((call) => call.name === name);

for (const width of [390, 320] as const)
  test(`Start opens on the day, every block in its order (${width}, light)`, async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await open(page, { width });
    const view = home(app);
    await expect(
      view.getByRole("heading", { level: 2, name: "Måndag 23 november" }),
    ).toBeVisible();
    expect(await calls(page, "get_start")).toHaveLength(1);
    const headings = await view
      .locator("h2, h3")
      .evaluateAll((items) => items.map((item) => item.textContent ?? ""));
    expect(headings).toEqual([
      "Måndag 23 november",
      "Redo att prata",
      "Morgonplan",
      "Idag (4)",
      "Väntar på andra (3)",
    ]);
    await expect(
      view.getByRole("button", { name: /^Förslag.*5 väntar på ditt svar/ }),
    ).toBeVisible();
    await expect(
      view.getByRole("button", { name: "Öppna Agenda · 1 till" }),
    ).toBeVisible();
    await expect(view.getByText("8 dagar försenad")).toHaveCSS(
      "color",
      /rgb\(180, 35, 24\)/,
    );
    await expectFits(app, view);
    await shot(page, `home-${width}-light-sv`);
    expect(failures).toEqual([]);
    expect(networkRequests()).toBe(0);
  });

test("the inbox and the automations are a row away, and Back returns to the day", async ({
  page,
}) => {
  const { app } = await open(page, { width: 390 });
  const row = home(app).getByRole("button", { name: /^Förslag/ });
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(
    app.getByRole("heading", { level: 2, name: "Förslag" }),
  ).toBeVisible();
  await expect(app.getByText("Säkra förslag (4)")).toBeVisible();
  await app.getByRole("button", { name: /^Tillbaka/ }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Måndag 23 november" }),
  ).toBeVisible();
  await home(app)
    .getByRole("button", { name: /^Automationer/ })
    .click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Automationer" }),
  ).toBeVisible();
});

test("a ready conversation is skipped for today, and Ångra brings it back", async ({
  page,
}) => {
  const { app } = await open(page, {
    width: 390,
    replies: {
      get_start: {
        __sequence: [
          { structuredContent: fullStart },
          { structuredContent: { ...fullStart, ready: undefined } },
          { structuredContent: fullStart },
        ],
      },
    },
  });
  const card = home(app).locator(".sk-decision", { hasText: "Morgonplan" });
  await expect(card.getByText("Redo sedan 07:00")).toBeVisible();
  // The instruction is never on the page: Claude reads it when it starts the conversation.
  await expect(
    app.getByText("Gå igenom dagens uppgifter med mig."),
  ).toHaveCount(0);
  await card.getByRole("button", { name: "Hoppa över idag" }).click();
  await expect(
    app.getByRole("status").filter({ hasText: "Hoppas över idag: Morgonplan" }),
  ).toBeVisible();
  await expect(
    home(app).getByRole("heading", { name: "Redo att prata" }),
  ).toHaveCount(0);
  await shot(page, "skipped-390-light-sv");
  await app.getByRole("button", { name: "Ångra" }).click();
  await expect(
    home(app).getByRole("heading", { name: "Morgonplan" }),
  ).toBeVisible();
  const skips = await calls(page, "skip_ready_conversation");
  expect(skips).toHaveLength(2);
  expect(skips[0]?.arguments).toMatchObject({
    conversation_id: homeIds.evening,
  });
  expect(skips[0]?.arguments).not.toHaveProperty("undo");
  expect(skips[1]?.arguments).toMatchObject({
    conversation_id: homeIds.evening,
    undo: true,
  });
  expect(skips[0]?.arguments.idempotency_key).not.toBe(
    skips[1]?.arguments.idempotency_key,
  );
});

test("a failed read offers Försök igen, which reads the day again", async ({
  page,
}) => {
  const { app } = await open(page, {
    width: 390,
    theme: "dark",
    replies: {
      get_start: {
        __sequence: [
          { isError: true, content: [{ type: "text", text: "boom" }] },
          { structuredContent: fullStart },
        ],
      },
    },
  });
  await expect(app.getByText("Startvyn kunde inte hämtas")).toBeVisible();
  await shot(page, "error-390-dark-sv");
  await app.getByRole("button", { name: "Försök igen" }).click();
  await expect(
    home(app).getByRole("heading", { level: 3, name: "Idag (4)" }),
  ).toBeVisible();
});

test("the English day reads in English (390, dark)", async ({ page }) => {
  const { app } = await open(page, { width: 390, theme: "dark", locale: "en" });
  const view = home(app);
  await expect(
    view.getByRole("heading", { level: 2, name: "Monday 23 November" }),
  ).toBeVisible();
  await expect(view.getByText("Ready to talk")).toBeVisible();
  await expect(view.getByRole("button", { name: "Skip today" })).toBeVisible();
  await expect(
    view.getByRole("button", { name: "Start", exact: true }),
  ).toBeVisible();
  await expect(
    view.getByRole("button", { name: "Open Agenda · 1 more" }),
  ).toBeVisible();
  await expect(view.getByText("Erik Sjöstrand · since 13 Nov")).toBeVisible();
  await expectFits(app, view);
  await shot(page, "home-390-dark-en");
});

for (const theme of ["dark", "light"] as const)
  test(`a wide frame puts the inbox beside the day (1440, ${theme})`, async ({
    page,
  }) => {
    const { app, failures } = await open(page, {
      width: 1440,
      height: 900,
      theme,
    });
    const aside = app.locator(".sk-split__aside");
    await expect(
      aside.getByRole("heading", { level: 2, name: "Förslag" }),
    ).toBeVisible();
    await expect(aside.getByText("Säkra förslag (4)")).toBeVisible();
    // The inbox stands beside the day, so the day draws no row to it.
    await expect(
      home(app).getByRole("button", { name: /^Förslag/ }),
    ).toHaveCount(0);
    const [column, side] = await Promise.all([
      home(app).boundingBox(),
      aside.boundingBox(),
    ]);
    expect(column && side && column.x + column.width <= side.x).toBe(true);
    await shot(page, `home-1440-${theme}`);
    expect(failures).toEqual([]);
  });
