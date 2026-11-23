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
  automationReplies,
  evening,
  invoices,
  morning,
} from "./automations-fixtures";
import { inboxPage, suggestionReplies } from "./suggestions-fixtures";

// The Start room's automations on the SIMULATED host (mcp-host-fixture.ts): every tool answer is a fixture, no backend,
// no database, no network. This is not a run in a real Claude or Android host, and it does not show the host's own
// confirmation of approve_automation (the tool no longer carries requiresUserInteraction). With AUTOMATION_SHOTS=<dir> each test also writes its
// screenshots there.

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
      toolInfo: { id: 1, tool: { name: "list_suggestions" } },
      platform: options.width >= 1024 ? "desktop" : "mobile",
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: { ...suggestionReplies, ...automationReplies, ...options.replies },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, inboxPage);
  await settled(opened.app);
  return opened;
}

async function shot(page: Page, name: string) {
  const out = process.env.AUTOMATION_SHOTS;
  if (!out) return;
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
}

/** From the inbox's row to the list, then to one automation. */
async function openAutomation(app: FrameLocator, title: string, sv = true) {
  await app
    .getByRole("button", {
      name: sv ? /^Automationer/ : /^Automations/,
    })
    .first()
    .click();
  await app.getByRole("button", { name: new RegExp(`^${title}`) }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: title }),
  ).toBeVisible();
}

const approveCalls = async (page: Page) =>
  (await simulatedHostState(page)).calls.filter(
    (call) => call.name === "approve_automation",
  );

test("the inbox leads to the automations, the ones that wait first", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await open(page, { width: 390 });
  const entry = app.getByRole("button", {
    name: /Automationer.*2 väntar på ditt godkännande/,
  });
  await expect(entry).toBeVisible();
  expect((await entry.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  await shot(page, "inbox-390-light-sv");
  await entry.click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Automationer" }),
  ).toBeVisible();
  const rows = app.locator(".start-automation-rows > li");
  await expect(rows).toHaveCount(4);
  await expect(rows.first()).toContainText("Fakturakoll");
  await expect(rows.first()).toContainText("Väntar på ditt godkännande");
  for (const box of await rows.evaluateAll((items) =>
    items.map((item) => item.getBoundingClientRect().height),
  ))
    expect(box).toBeGreaterThanOrEqual(44);
  await shot(page, "list-390-light-sv");
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("an automation that applies without a click asks in its own step, and only then sends the confirmation", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await open(page, { width: 390 });
  await openAutomation(app, "Fakturakoll");
  await expect(
    app.getByText(
      "Lägger in nya uppgifter utan att fråga när kontrollen är minst 95 % säker",
    ),
  ).toBeVisible();
  await shot(page, "detail-390-light-sv");

  await app.getByRole("button", { name: "Godkänn…" }).click();
  expect(await approveCalls(page)).toHaveLength(0);
  const step = app.getByRole("group", {
    name: "Den lägger in förslag utan att fråga dig",
  });
  await expect(step).toBeVisible();
  await expect(step.getByRole("heading", { level: 4 })).toBeFocused();
  const check = step.locator("label.start-confirm-check");
  expect((await check.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  for (const name of ["Avbryt", "Godkänn"])
    expect(
      (await step.getByRole("button", { name, exact: true }).boundingBox())
        ?.height ?? 0,
    ).toBeGreaterThanOrEqual(44);
  await step.scrollIntoViewIfNeeded();
  await shot(page, "confirm-390-light-sv");

  // A double press on Godkänn without the box sends nothing.
  // aria-disabled, so Playwright would wait: the press is forced, as a person can press it.
  await step
    .getByRole("button", { name: "Godkänn", exact: true })
    .dblclick({ force: true });
  expect(await approveCalls(page)).toHaveLength(0);
  await expect(app.getByText("Kryssa i rutan först")).toBeVisible();

  await step.getByRole("checkbox").check();
  await step.getByRole("button", { name: "Godkänn", exact: true }).click();
  await expect(
    app.getByRole("status").filter({ hasText: "Godkänd: Fakturakoll" }),
  ).toBeVisible();
  const calls = await approveCalls(page);
  expect(calls).toHaveLength(1);
  expect(calls[0]?.arguments).toMatchObject({
    automation_id: invoices.id,
    spec_digest: invoices.spec_digest,
    auto_apply_confirmed: true,
  });
  await expect(
    app.getByText("Den får lägga in förslag utan att fråga."),
  ).toBeVisible();
  await shot(page, "approved-390-light-sv");
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("an automation that only proposes is approved with its digest alone", async ({
  page,
}) => {
  const { app } = await open(page, { width: 360, theme: "dark" });
  await openAutomation(app, "Kvällsgenomgång");
  await expect(
    app.getByText("Den körs inte förrän du har godkänt den nya versionen."),
  ).toBeVisible();
  await app.getByRole("button", { name: "Godkänn", exact: true }).click();
  await expect(
    app.getByRole("status").filter({ hasText: "Godkänd: Kvällsgenomgång" }),
  ).toBeVisible();
  const calls = await approveCalls(page);
  expect(calls).toHaveLength(1);
  expect(calls[0]?.arguments).toMatchObject({
    automation_id: evening.id,
    spec_digest: evening.spec_digest,
  });
  expect(calls[0]?.arguments).not.toHaveProperty("auto_apply_confirmed");
  await shot(page, "approved-360-dark-sv");
});

for (const theme of ["light", "dark"] as const)
  test(`a wide frame opens an automation beside the list (${theme})`, async ({
    page,
  }) => {
    const { app } = await open(page, { width: 1440, height: 900, theme });
    await app
      .getByRole("button", { name: /^Automationer/ })
      .first()
      .click();
    await expect(
      app.getByText("Välj en automation för att se den här").first(),
    ).toBeVisible();
    await app.getByRole("button", { name: /^Morgonmejl/ }).click();
    const detail = app.locator("[data-pane='detail']");
    await expect(
      detail.getByRole("heading", { level: 2, name: "Morgonmejl" }),
    ).toBeVisible();
    await expect(
      detail.getByText(
        "3 körningar · 1 misslyckades · 7 förslag · 3 väntar · 0,09 USD",
        { exact: false },
      ),
    ).toBeVisible();
    await expect(
      app.locator(`[data-sk-record="start:automation:${morning.id}"]`),
    ).toHaveAttribute("aria-current", "true");
    await shot(page, `detail-1440-${theme}`);
    await app.getByRole("button", { name: /^Fakturakoll/ }).click();
    await detail.getByRole("button", { name: "Godkänn…" }).click();
    await expect(
      detail.getByRole("group", {
        name: "Den lägger in förslag utan att fråga dig",
      }),
    ).toBeVisible();
    await shot(page, `confirm-1440-${theme}`);
  });

test("the English automation reads in English", async ({ page }) => {
  const { app } = await open(page, { width: 390, locale: "en", theme: "dark" });
  await openAutomation(app, "Fakturakoll", false);
  await expect(
    app.locator(".start-automation-state", {
      hasText: "Waits for your approval",
    }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Approve…" }).click();
  await expect(
    app.getByRole("group", { name: "It adds suggestions without asking you" }),
  ).toBeVisible();
  await expect(
    app.getByRole("checkbox", {
      name: "I want it to add these suggestions without asking me",
    }),
  ).toBeVisible();
  await shot(page, "confirm-390-dark-en");
});

test("a failed read of the automations offers Försök igen", async ({
  page,
}) => {
  const { app } = await open(page, {
    width: 390,
    replies: {
      list_automations: {
        __sequence: [
          { structuredContent: { items: [], next_cursor: null } },
          { isError: true, content: [{ type: "text", text: "boom" }] },
          {
            structuredContent:
              automationReplies.list_automations.structuredContent,
          },
        ],
      },
    },
  });
  // No automation yet: the inbox draws no row, and its ⋯ still leads there.
  await expect(app.getByRole("button", { name: /^Automationer/ })).toHaveCount(
    0,
  );
  await app.getByRole("button", { name: "Fler val för Förslag" }).click();
  await app.getByRole("button", { name: "Automationer" }).click();
  await expect(app.getByText("Automationerna kunde inte hämtas")).toBeVisible();
  await shot(page, "error-390");
  await app.getByRole("button", { name: "Försök igen" }).click();
  await expect(app.locator(".start-automation-rows > li")).toHaveCount(4);
});

for (const width of [320, 412] as const)
  test(`the detail and its confirmation fit a ${width} frame`, async ({
    page,
  }) => {
    const { app } = await open(page, { width });
    await openAutomation(app, "Fakturakoll");
    await app.getByRole("button", { name: "Godkänn…" }).click();
    const step = app.locator(".start-confirm");
    await step.scrollIntoViewIfNeeded();
    const measures = await step.evaluate((element) => {
      const root = element.ownerDocument.documentElement;
      const box = element.getBoundingClientRect();
      const controls = [...element.querySelectorAll("button, label")].map(
        (control) => control.getBoundingClientRect(),
      );
      return {
        overflow: root.scrollWidth - root.clientWidth,
        right: box.right,
        frame: root.clientWidth,
        lowest: Math.min(...controls.map((rect) => rect.height)),
        widest: Math.max(...controls.map((rect) => rect.right)),
      };
    });
    expect(measures.overflow).toBeLessThanOrEqual(0);
    expect(measures.right).toBeLessThanOrEqual(measures.frame);
    expect(measures.widest).toBeLessThanOrEqual(measures.frame);
    expect(measures.lowest).toBeGreaterThanOrEqual(44);
    await shot(page, `confirm-${width}-light-sv`);
  });
