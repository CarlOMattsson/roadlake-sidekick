import { mkdirSync } from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type FrameLocator, type Page } from "@playwright/test";

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

// The review card (work-app/review): get_review_queue's page walked through one Task at a time inline. SIMULATED host
// (mcp-host-fixture.ts): every tool answer is a fixture. Not a test in a real Claude or Android host.
// REVIEW_WALK_OUT=<dir> also writes the screenshots.

const OUT = process.env.REVIEW_WALK_OUT ?? "";
const NOW = new Date("2026-11-20T09:00:00+01:00");

test.beforeAll(() => {
  if (OUT) mkdirSync(OUT, { recursive: true });
});

function queueTask(
  n: number,
  title: string,
  bucket: string,
  extra: Record<string, unknown> = {},
) {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    version: 3,
    title,
    status: "todo",
    bucket,
    reason: "overdue 3 weeks",
    due_at: "2026-10-28T22:59:00Z",
    follow_up_at: null,
    project_id: null,
    project_title: null,
    domain_id: null,
    domain_name: null,
    ...extra,
  };
}

const firstPage = {
  tasks: [
    queueTask(1, "Skicka offerten till Holm Bygg", "likely_done", {
      project_title: "Kundupdrag Holm",
    }),
    queueTask(2, "Boka service för bilen", "long_overdue", {
      domain_name: "Hem",
    }),
    queueTask(3, "Ring tillbaka om hyresavtalet", "follow_up_due", {
      due_at: null,
      follow_up_at: "2026-11-17T22:59:00Z",
    }),
    queueTask(4, "Läs igenom styrelseprotokollet", "overdue"),
  ],
  scope: "suggested",
  remaining_total: 120,
  bucket_counts: { likely_done: 12, long_overdue: 40, overdue: 68 },
  next_cursor: "cursor-2",
};
const secondPage = {
  tasks: [
    queueTask(5, "Sortera kvittona från oktober", "overdue"),
    queueTask(6, "Byt lösenord på routern", "overdue"),
  ],
  scope: "suggested",
  remaining_total: 116,
  bucket_counts: { overdue: 116 },
  next_cursor: null,
};

function reviewed(n: number, decision: string, status: string) {
  return {
    count: 1,
    tasks: [
      {
        id: firstPage.tasks[n - 1]!.id,
        version: 4,
        decision,
        status,
        due_at: "2026-10-28T22:59:00Z",
        archived: false,
        previous: {
          status: "todo",
          due_at: "2026-10-28T22:59:00Z",
          waiting_since: null,
          follow_up_at: null,
          attention_requested: false,
          last_completed_at: null,
          archived_at: null,
        },
      },
    ],
  };
}

const replies = {
  review_tasks: { structuredContent: reviewed(1, "done", "completed") },
  get_review_queue: { structuredContent: secondPage },
  update_task: {
    structuredContent: {
      task: {
        id: firstPage.tasks[0]!.id,
        version: 5,
        title: firstPage.tasks[0]!.title,
        status: "todo",
        due_at: "2026-10-28T22:59:00Z",
      },
    },
  },
  move_to_trash: { structuredContent: { version: 1 } },
  restore_from_trash: { structuredContent: { version: 2 } },
  get_task: {
    structuredContent: {
      task: {
        id: firstPage.tasks[0]!.id,
        version: 6,
        title: firstPage.tasks[0]!.title,
        status: "todo",
        due_at: "2026-10-28T22:59:00Z",
      },
    },
  },
};

type View = {
  width: number;
  theme?: "light" | "dark";
  locale?: AppLocale;
};

async function openReview(page: Page, view: View) {
  const { width, theme = "light", locale = "sv" } = view;
  await page.clock.setFixedTime(NOW);
  await page.emulateMedia({ colorScheme: theme });
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", locale),
    width,
    height: 900,
    hostContext: {
      locale,
      theme,
      displayMode: "inline",
      availableDisplayModes: ["inline", "fullscreen"],
      platform: "mobile",
      toolInfo: { id: 1, tool: { name: "get_review_queue" } },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies,
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, firstPage);
  await settled(opened.app);
  return opened;
}

const card = (app: FrameLocator) => app.locator(".review-walk");

/** The inline card's height as a host sizes the iframe: the lowest bottom edge of the content. */
function contentHeight(app: FrameLocator) {
  return app.locator("html").evaluate(() => {
    let bottom = 0;
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      const r = el.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) continue;
      bottom = Math.max(bottom, r.bottom + window.scrollY);
    }
    return Math.ceil(bottom);
  });
}

async function shot(page: Page, app: FrameLocator, name: string) {
  if (!OUT) return;
  const height = await contentHeight(app);
  await page.screenshot({
    path: path.join(OUT, `${name}.png`),
    clip: { x: 0, y: 0, width: page.viewportSize()!.width, height: height + 8 },
    animations: "disabled",
  });
}

async function targets(app: FrameLocator) {
  const buttons = card(app).locator("button:visible");
  const sizes: { text: string; height: number; width: number }[] = [];
  for (let i = 0; i < (await buttons.count()); i++) {
    const button = buttons.nth(i);
    const size = await effectiveTargetSize(button);
    sizes.push({
      text: (await button.innerText()).trim(),
      height: size?.height ?? 0,
      width: size?.width ?? 0,
    });
  }
  return sizes;
}

for (const view of [
  { width: 390, theme: "light", locale: "sv" },
  { width: 390, theme: "dark", locale: "sv" },
  { width: 390, theme: "light", locale: "en" },
  { width: 360, theme: "dark", locale: "en" },
  { width: 320, theme: "light", locale: "sv" },
  { width: 740, theme: "light", locale: "sv" },
] as const) {
  test(`review card ${view.width} ${view.theme} ${view.locale}: one Task, under 340 with the receipt, 48 targets`, async ({
    page,
  }) => {
    const { app, failures, networkRequests } = await openReview(page, view);
    const sv = view.locale === "sv";
    await expect(card(app)).toBeVisible();
    await expect(card(app)).toContainText(sv ? "1 av 120" : "1 of 120");
    await expect(
      card(app).getByRole("heading", { name: firstPage.tasks[0]!.title }),
    ).toBeVisible();
    await expect(card(app)).toContainText(
      sv
        ? "Alla steg klara · Kundupdrag Holm"
        : "All steps done · Kundupdrag Holm",
    );
    const decisions = card(app).getByRole("group", {
      name: sv
        ? "Vad ska hända med uppgiften?"
        : "What should happen to the task?",
    });
    await expect(decisions.getByRole("button")).toHaveText(
      sv
        ? ["Klar", "Behåll", "Flytta", "Ta bort"]
        : ["Done", "Keep", "Move", "Delete"],
    );
    // No inner scroll, no room strip, nothing wider than the frame.
    await expect(app.locator(".sk-rooms")).toHaveCount(0);
    const horizontal = await app
      .locator("html")
      .evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
    expect(horizontal).toBe(false);
    for (const target of await targets(app)) {
      expect(target.height, target.text).toBeGreaterThanOrEqual(48);
      expect(target.width, target.text).toBeGreaterThanOrEqual(48);
    }
    const name = `${view.width}-${view.theme}-${view.locale}`;
    await shot(page, app, `${name}-1-task`);
    const before = await contentHeight(app);
    console.log(`HEIGHT ${name} task: ${before}`);
    expect(before).toBeLessThan(340);

    // Klar: saved, the next Task, and the receipt with Ångra; still under 340.
    await decisions.getByRole("button", { name: sv ? "Klar" : "Done" }).click();
    await expect(card(app)).toContainText(sv ? "2 av 120" : "2 of 120");
    const undo = card(app).getByRole("button", { name: sv ? "Ångra" : "Undo" });
    await expect(undo).toBeVisible();
    await expect(card(app).locator(".sk-receipt-slot")).toContainText(
      sv ? "Klar: Skicka offerten" : "Done: Skicka offerten",
    );
    await settled(app);
    await shot(page, app, `${name}-2-receipt`);
    const withReceipt = await contentHeight(app);
    console.log(`HEIGHT ${name} receipt: ${withReceipt}`);
    expect(withReceipt).toBeLessThan(340);
    for (const target of await targets(app)) {
      expect(target.height, target.text).toBeGreaterThanOrEqual(48);
    }

    // Flytta turns the row in place: as high as before.
    const rowHeight = (await decisions.boundingBox())!.height;
    await decisions
      .getByRole("button", { name: sv ? "Flytta" : "Move" })
      .click();
    const days = card(app).getByRole("group", {
      name: sv ? "Flytta till" : "Move to",
    });
    await expect(days.getByRole("button")).toHaveText(
      sv
        ? ["Imorgon", "Nästa vecka", "Avbryt"]
        : ["Tomorrow", "Next week", "Cancel"],
    );
    if (view.width >= 360)
      expect(
        Math.abs((await days.boundingBox())!.height - rowHeight),
      ).toBeLessThan(1);
    await shot(page, app, `${name}-3-move`);

    expect(networkRequests()).toBe(0);
    expect(failures).toEqual([]);
  });
}

test("each tap saves one Task through review_tasks, Ångra writes it back and shows it again", async ({
  page,
}) => {
  const { app, failures } = await openReview(page, { width: 390 });
  await card(app).getByRole("button", { name: "Klar" }).click();
  await expect(card(app)).toContainText("2 av 120");
  let state = await simulatedHostState(page);
  const reviews = state.calls.filter((call) => call.name === "review_tasks");
  expect(reviews).toHaveLength(1);
  // One Task per call: the card never changes more Tasks than the owner just saw (the voice rule allows three).
  expect(reviews[0]!.arguments.items).toEqual([
    {
      task_id: firstPage.tasks[0]!.id,
      expected_version: 3,
      decision: "done",
    },
  ]);
  expect(state.modelContexts.at(-1)).toContain("1 beslut sparade");

  await card(app).getByRole("button", { name: "Ångra" }).click();
  await expect(card(app)).toContainText("1 av 120");
  await expect(
    card(app).getByRole("heading", { name: firstPage.tasks[0]!.title }),
  ).toBeVisible();
  state = await simulatedHostState(page);
  const update = state.calls.find((call) => call.name === "update_task");
  expect(update?.arguments).toMatchObject({
    task_id: firstPage.tasks[0]!.id,
    version: 4,
    changes: { status: "todo" },
  });
  expect(failures).toEqual([]);
});

test("Flytta and Imorgon move by review_tasks; the keyboard reaches every choice", async ({
  page,
}) => {
  const { app, failures } = await openReview(page, { width: 390 });
  const move = card(app).getByRole("button", { name: "Flytta" });
  await move.focus();
  await page.keyboard.press("Enter");
  const tomorrow = card(app).getByRole("button", { name: "Imorgon" });
  await expect(tomorrow).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(card(app).getByRole("button", { name: "Avbryt" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(move).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(tomorrow).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(card(app)).toContainText("2 av 120");
  const state = await simulatedHostState(page);
  const review = state.calls.find((call) => call.name === "review_tasks");
  expect(review?.arguments.items).toEqual([
    {
      task_id: firstPage.tasks[0]!.id,
      expected_version: 3,
      decision: "move",
      when: "tomorrow",
    },
  ]);
  expect(failures).toEqual([]);
});

test("Ta bort goes through the trash and Ångra takes it back", async ({
  page,
}) => {
  const { app, failures } = await openReview(page, { width: 390 });
  await card(app).getByRole("button", { name: "Ta bort" }).click();
  await expect(card(app)).toContainText("2 av 120");
  await expect(card(app).locator(".sk-receipt-slot")).toContainText(
    "Borttagen:",
  );
  await card(app).getByRole("button", { name: "Ångra" }).click();
  await expect(card(app)).toContainText("1 av 120");
  const names = (await simulatedHostState(page)).calls.map((call) => call.name);
  expect(names).toEqual(
    expect.arrayContaining(["move_to_trash", "restore_from_trash", "get_task"]),
  );
  expect(names).not.toContain("review_tasks");
  expect(failures).toEqual([]);
});

test("the next page is read ahead with the same scope and cursor, and the walk ends with a tally", async ({
  page,
}) => {
  const { app, failures } = await openReview(page, { width: 390 });
  const skip = card(app).getByRole("button", { name: "Hoppa över" });
  await skip.click();
  await expect(card(app)).toContainText("2 av 120");
  const read = (await simulatedHostState(page)).calls.find(
    (call) => call.name === "get_review_queue",
  );
  expect(read?.arguments).toEqual({ scope: "suggested", cursor: "cursor-2" });
  for (let n = 2; n <= 6; n++) await skip.click();
  await expect(card(app)).toContainText("Genomgången är klar");
  await expect(card(app)).toContainText("0 beslut · 6 hoppade över");
  await shot(page, app, "390-light-sv-4-finished");
  expect(failures).toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`axe finds nothing on the review card, ${theme}, with the receipt and the move row`, async ({
    page,
  }) => {
    const { app, failures } = await openReview(page, { width: 390, theme });
    await card(app).getByRole("button", { name: "Klar" }).click();
    await card(app).getByRole("button", { name: "Flytta" }).click();
    await settled(app);
    // The app's root is transparent; a real host paints the page, the simulated one does not.
    await app.locator("html").evaluate((root, dark) => {
      root.style.backgroundColor = dark ? "#1c1c1e" : "#ffffff";
    }, theme === "dark");
    const results = await new AxeBuilder({ page })
      .include("iframe")
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map((violation) => ({
        rule: violation.id,
        targets: violation.nodes.map((node) => node.target.join(" ")),
      })),
    ).toEqual([]);
    expect(failures).toEqual([]);
  });
}
