import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
  FIXTURE_NOW,
  bigAgenda,
  bigBoard,
  bigContactList,
  bigHierarchy,
  bigJournalDay,
  bigShoppingDetail,
  controlReplies,
  fullTask,
  journalReplies,
  memoryStatus,
  shoppingReplies,
  workReplies,
} from "./one-screen-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import type { AppLocale } from "./mcp-host-fixture";

// AUTOMATED AXE CHECK of the rooms (Work, Journal, Shopping and Control) in the SIMULATED host (see
// mcp-host-fixture.ts): every tool answer and host message is a fixture, so this is not a real
// Claude or Sidekick host. axe-core covers the WCAG 2.0/2.1 A and AA rules (including colour
// contrast in both themes) on what the built app draws inside the sandboxed iframe. It finds the
// problems a machine can find; keyboard flow and touch targets are covered by
// a11y-mobile-mcp-app.spec.ts, and a screen reader pass on a real host is still manual.

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

type Scenario = {
  name: string;
  resource: "work" | "journal" | "shopping" | "control";
  result: unknown;
  replies: Record<string, unknown>;
};

const scenarios: Scenario[] = [
  {
    name: "work agenda",
    resource: "work",
    result: bigAgenda,
    replies: workReplies,
  },
  {
    name: "work board",
    resource: "work",
    result: bigBoard,
    replies: workReplies,
  },
  {
    name: "work hierarchy",
    resource: "work",
    result: bigHierarchy,
    replies: workReplies,
  },
  {
    name: "work contacts",
    resource: "work",
    result: bigContactList,
    replies: workReplies,
  },
  {
    name: "work task",
    resource: "work",
    result: { task: fullTask },
    replies: workReplies,
  },
  {
    name: "journal day",
    resource: "journal",
    result: bigJournalDay,
    replies: journalReplies,
  },
  {
    name: "journal entry",
    resource: "journal",
    result: { entry: bigJournalDay.entries[0] },
    replies: journalReplies,
  },
  {
    name: "shopping list",
    resource: "shopping",
    result: bigShoppingDetail,
    replies: shoppingReplies,
  },
  {
    name: "control memory",
    resource: "control",
    result: memoryStatus,
    replies: controlReplies,
  },
];

const modes = [
  // Fullscreen shows the room strip and the whole view; inline shows the compact card.
  { display: "fullscreen", theme: "light", locale: "sv" },
  { display: "fullscreen", theme: "dark", locale: "en" },
  { display: "inline", theme: "light", locale: "en" },
  { display: "inline", theme: "dark", locale: "sv" },
] as const;

for (const scenario of scenarios) {
  for (const mode of modes) {
    test(`simulated host: axe finds no WCAG A/AA violations in ${scenario.name} (${mode.display}, ${mode.theme}, ${mode.locale})`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(FIXTURE_NOW);
      const { failures } = await openSimulatedApp(page, {
        resource: readBuiltApp(scenario.resource, mode.locale as AppLocale),
        width: 390,
        height: 844,
        hostContext: {
          locale: mode.locale,
          theme: mode.theme,
          displayMode: mode.display,
          availableDisplayModes: ["inline", "fullscreen"],
        },
        hostCapabilities: { serverTools: {}, message: {} },
        replies: scenario.replies,
      });
      await waitForAppInitialized(page);
      await deliverToolResult(page, scenario.result);
      const app = page.frameLocator("iframe");
      await settled(app);
      // The app's root is transparent by design: the host paints the page. A real host does, the simulated
      // one does not, and axe cannot see the outer page across the iframe, so paint the app's dark fallback surface.
      await app.locator("html").evaluate((root, theme) => {
        root.style.backgroundColor = theme === "dark" ? "#1c1c1e" : "#ffffff";
      }, mode.theme);

      const results = await new AxeBuilder({ page })
        .include("iframe")
        .withTags(WCAG_TAGS)
        .analyze();
      const found = results.violations.map((violation) => ({
        rule: violation.id,
        impact: violation.impact,
        targets: violation.nodes.map((node) => node.target.join(" ")),
      }));
      expect(found).toEqual([]);
      expect(failures).toEqual([]);
    });
  }
}
