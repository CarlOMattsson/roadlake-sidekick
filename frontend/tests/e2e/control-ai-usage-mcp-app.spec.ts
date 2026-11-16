import { expect, test, type Page } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// The AI cost row in Control's full view, in a real Chromium on the simulated host (mcp-host-fixture.ts), not a real
// Claude or Android host. It is drawn and read only where the instance switched it on (SIDEKICK_MCP_APP_SHOW_AI_USAGE,
// the app document's meta); off, the app never calls get_ai_usage.

/** Set it to a folder to also write a screenshot of every case there. */
const SHOTS = process.env.CONTROL_SHOTS_DIR;
const SHOWN = '<meta name="sidekick-ai-usage" content="on">';
const usage = {
  month_starts_at: "2026-11-01T00:00:00Z",
  spent_usd: 0.42,
  client_estimate_usd: 0.1,
  monthly_cap_usd: 5,
  starts_today: 3,
  daily_starts_cap: 50,
};

async function openControl(
  page: Page,
  options: {
    shown: boolean;
    locale: "sv" | "en";
    width: number;
    theme: "light" | "dark";
  },
) {
  await page.emulateMedia({ colorScheme: options.theme });
  const html = readBuiltApp("control", options.locale);
  const { app, failures } = await openSimulatedApp(page, {
    resource: options.shown ? html.replace("<head>", `<head>${SHOWN}`) : html,
    width: options.width,
    height: 780,
    hostContext: {
      locale: options.locale,
      theme: options.theme,
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: "list_trash" } },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: { get_ai_usage: { structuredContent: usage } },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, {
    items: [],
    has_more: false,
    next_cursor: null,
  });
  return { app, failures };
}

const calls = async (page: Page) =>
  (await simulatedHostState(page)).calls.map((call) => call.name);

for (const width of [320, 412])
  for (const theme of ["light", "dark"] as const)
    for (const locale of ["sv", "en"] as const)
      test(`switched on, Control shows the month's AI cost (${locale}, ${width} px, ${theme})`, async ({
        page,
      }) => {
        const { app, failures } = await openControl(page, {
          shown: true,
          locale,
          width,
          theme,
        });
        const spent = app.getByText(
          locale === "sv" ? "0,42 USD av 5,00 USD" : "0.42 USD of 5.00 USD",
        );
        await expect(spent).toBeVisible();
        await expect(
          app.getByText(
            locale === "sv"
              ? "3 av 50 starter i dag · 0,10 USD uppskattat av Claude Code"
              : "3 of 50 starts today · 0.10 USD estimated by Claude Code",
          ),
        ).toBeVisible();
        // The row stays inside the view at a phone's width: nothing runs past the right edge.
        const row = app.locator(".control-ai-usage");
        const fits = await row.evaluate(
          (el) =>
            el.getBoundingClientRect().right <=
              document.documentElement.clientWidth &&
            el.scrollWidth <= el.clientWidth,
        );
        expect(fits).toBe(true);
        expect((await calls(page)).filter((n) => n === "get_ai_usage")).toEqual(
          ["get_ai_usage"],
        );
        if (SHOTS)
          await page.screenshot({
            path: `${SHOTS}/control-ai-usage-${locale}-${width}-${theme}.png`,
          });
        expect(failures).toEqual([]);
      });

test("off by default: Control draws no AI cost and never calls get_ai_usage", async ({
  page,
}) => {
  const { app, failures } = await openControl(page, {
    shown: false,
    locale: "sv",
    width: 375,
    theme: "light",
  });
  await expect(app.getByText("Inget borttaget.")).toBeVisible();
  await expect(app.getByText(/AI denna månad/)).toHaveCount(0);
  expect(await calls(page)).not.toContain("get_ai_usage");
  expect(failures).toEqual([]);
});
