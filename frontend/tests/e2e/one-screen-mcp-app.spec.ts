import { mkdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { FrameLocator, Page } from "@playwright/test";
import {
  FIXTURE_NOW,
  bigActivity,
  bigAgenda,
  bigBoard,
  bigChanges,
  bigContactContext,
  bigContactList,
  bigHierarchy,
  bigJournalDay,
  bigJournalPending,
  bigShoppingBatch,
  bigShoppingDetail,
  bigTrash,
  bigWorkChanges,
  contactRecord,
  controlReplies,
  fullTask,
  journalReplies,
  memoryStatus,
  projectRecord,
  shoppingReplies,
  threeStoreShoppingDetail,
  workReplies,
} from "./one-screen-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// ONE CARD, ONE SCREEN: an inline card in the chat fits a phone screen,
// at most 560 px high including the card frame, at 375 and 320 px wide, light and dark, even with
// realistic amounts of data (25 agenda tasks, 40 shopping items, 8 journal entries, 30 trash items,
// 15 steps). The rest is reached through "Show all" / "Open" (fullscreen), or by expanding inline
// when the host offers no fullscreen. Fullscreen may scroll and is not measured here.
// Simulated host only: no backend, no database, no network.
//
// ONE_SCREEN_ONLY=<regex> runs only the scenarios whose name matches, e.g. ONE_SCREEN_ONLY=^shopping.
// The clock is fixed at FIXTURE_NOW for every test (fixtures and browser alike), so due chips and row
// wrapping do not depend on the day or hour of the run. ONE_SCREEN_NOW=<ISO> moves it for a date sweep.
// ONE_SCREEN_SHOTS=<dir> also writes a 375 px light screenshot of each card to that folder.

const MAX_CARD_HEIGHT = 560;

const ONLY = process.env.ONE_SCREEN_ONLY
  ? new RegExp(process.env.ONE_SCREEN_ONLY)
  : undefined;
const SHOTS = process.env.ONE_SCREEN_SHOTS;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

const hostInline = (theme: string) => ({
  locale: "sv",
  theme,
  displayMode: "inline",
  availableDisplayModes: ["inline"],
});
const hostOffer = (theme: string) => ({
  locale: "sv",
  theme,
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
});

type Step = (app: FrameLocator, page: Page) => Promise<void>;
type Scenario = {
  name: string;
  resource: "work" | "journal" | "shopping" | "control";
  result: unknown;
  replies: Record<string, unknown>;
  /** Interactions before measuring (for example choosing a tab). */
  steps?: Step;
};
const scenarios: Scenario[] = [
  // ----- Work -----
  {
    name: "work-agenda",
    resource: "work",
    result: bigAgenda,
    replies: workReplies,
  },
  {
    name: "work-tavla",
    resource: "work",
    result: bigBoard,
    replies: workReplies,
  },
  {
    name: "work-hierarki",
    resource: "work",
    result: bigHierarchy,
    replies: workReplies,
  },
  {
    name: "work-kontakter",
    resource: "work",
    result: bigContactList,
    replies: workReplies,
  },
  {
    name: "work-andringar",
    resource: "work",
    result: bigWorkChanges,
    replies: workReplies,
  },
  {
    name: "work-uppgift",
    resource: "work",
    result: { task: fullTask },
    replies: workReplies,
  },
  {
    name: "work-projekt",
    resource: "work",
    result: { project: projectRecord },
    replies: workReplies,
  },
  {
    name: "work-kontakt-detalj",
    resource: "work",
    result: bigContactContext,
    replies: workReplies,
  },
  {
    name: "work-kontakt-kort",
    resource: "work",
    result: { contact: contactRecord(0, "Anna Andersson") },
    replies: workReplies,
  },
  // ----- Journal -----
  {
    name: "journal-dag",
    resource: "journal",
    result: bigJournalDay,
    replies: journalReplies,
  },
  {
    name: "journal-post",
    resource: "journal",
    result: { entry: bigJournalDay.entries[0] },
    replies: journalReplies,
  },
  {
    name: "journal-vantande",
    resource: "journal",
    result: bigJournalPending,
    replies: journalReplies,
  },
  {
    name: "journal-utkast",
    resource: "journal",
    result: { draft: { id: "019f0000-0000-7000-8800-000000000001" } },
    replies: journalReplies,
  },
  // ----- Shopping -----
  {
    name: "shopping-lista",
    resource: "shopping",
    result: bigShoppingDetail,
    replies: shoppingReplies,
  },
  {
    name: "shopping-batch",
    resource: "shopping",
    result: bigShoppingBatch,
    replies: shoppingReplies,
  },
  {
    name: "shopping-tre-butiker",
    resource: "shopping",
    result: threeStoreShoppingDetail,
    replies: {
      ...shoppingReplies,
      get_shopping_list: { structuredContent: threeStoreShoppingDetail },
    },
  },
  // ----- Control -----
  {
    name: "control-papperskorg",
    resource: "control",
    result: bigTrash,
    replies: controlReplies,
  },
  {
    name: "control-andringar",
    resource: "control",
    result: bigChanges,
    replies: controlReplies,
  },
  {
    name: "control-aktivitet",
    resource: "control",
    result: bigActivity,
    replies: controlReplies,
  },
  {
    name: "control-minne",
    resource: "control",
    result: memoryStatus,
    replies: controlReplies,
  },
];

/** Every combination is a test: the stricter host (no fullscreen) in all four, the offering host in two. */
const combos = [
  { host: "inline", offer: false, width: 375, theme: "light" },
  { host: "inline", offer: false, width: 375, theme: "dark" },
  { host: "inline", offer: false, width: 320, theme: "light" },
  { host: "inline", offer: false, width: 320, theme: "dark" },
  { host: "offer", offer: true, width: 375, theme: "light" },
  { host: "offer", offer: true, width: 320, theme: "dark" },
] as const;

/** Height of the card as an inline host would size the iframe: the lowest bottom edge of the content. */
function measureInFrame() {
  const root = document.getElementById("root");
  let bottom = 0;
  for (const el of Array.from(document.body.querySelectorAll("*"))) {
    const r = el.getBoundingClientRect();
    // Visually hidden helper text (1 px boxes) does not take room.
    if (r.width <= 1 || r.height <= 1) continue;
    if (getComputedStyle(el).position === "fixed") continue;
    bottom = Math.max(bottom, r.bottom + window.scrollY);
  }
  const rootRect = root?.getBoundingClientRect();
  return {
    height: Math.ceil(Math.max(bottom, rootRect ? rootRect.bottom : 0)),
    horizontal: document.documentElement.scrollWidth > window.innerWidth + 1,
    text: (document.body.innerText ?? "").slice(0, 80).replace(/\s+/g, " "),
  };
}

for (const scenario of scenarios) {
  if (ONLY && !ONLY.test(scenario.name)) continue;
  for (const combo of combos) {
    test(`one screen: ${scenario.name} ${combo.host} ${combo.width} ${combo.theme}`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(FIXTURE_NOW);
      const opened = await openSimulatedApp(page, {
        resource: readBuiltApp(scenario.resource, "sv"),
        width: combo.width,
        height: 1600,
        hostContext: (combo.offer ? hostOffer : hostInline)(combo.theme),
        // A host that proxies tools: the strip would show here if inline cards had one.
        hostCapabilities: { serverTools: {}, message: {} },
        replies: scenario.replies,
      });
      await waitForAppInitialized(page);
      await deliverToolResult(page, scenario.result);
      await settled(opened.app);
      if (scenario.steps) await scenario.steps(opened.app, page);
      const measured = await opened.app
        .locator("html")
        .evaluate(measureInFrame);
      if (
        SHOTS &&
        combo.host === "inline" &&
        combo.width === Number(process.env.ONE_SCREEN_SHOT_WIDTH ?? 375) &&
        combo.theme === "light"
      ) {
        await page.screenshot({
          path: `${SHOTS}/${scenario.name}.png`,
          clip: {
            x: 0,
            y: 0,
            width: combo.width,
            height: Math.min(measured.height + 8, 2400),
          },
        });
      }
      console.log(
        `HEIGHT ${scenario.name} ${combo.host} ${combo.width} ${combo.theme}: ${measured.height}`,
      );
      expect(measured.horizontal, "no horizontal overflow").toBe(false);
      await expect(
        opened.app.locator(".sk-rooms"),
        "no room strip in an inline card",
      ).toHaveCount(0);
      expect(
        measured.height,
        `card height (${measured.text})`,
      ).toBeLessThanOrEqual(MAX_CARD_HEIGHT);
      expect(opened.failures).toEqual([]);
    });
  }
}
