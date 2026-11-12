import { test, expect, type Frame, type Page } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// SIMULATED HOST first-render timing (see mcp-host-fixture.ts). It is not a real Claude or Sidekick
// host: every tool answer and host message is a fixture. The apps run under 4x CPU throttling
// (CDP Emulation.setCPUThrottlingRate).
//
// The time to first card is measured INSIDE the browser with its own clock (performance.timeOrigin +
// performance.now()): from the moment the host page posts the tool-result message to the first
// animation frame after the first real card or view is in the app's DOM. Playwright round trips and the Node test runner's clock are not part of it,
// so a busy runner no longer inflates the number with wall-clock noise that is not the app's
// (the earlier Node-side Date.now() measurement flaked at 893 ms against 500 ms for that reason).
// CPU contention still slows the app itself under the throttle, which is why the ceiling keeps a
// wide margin and the "perf" project retries once.
// Values are printed with console.log.

const CPU_THROTTLE_RATE = 4;
const SKELETON = "[role='status'][aria-busy='true']";

// Ceiling per app for the in-browser time from tool-result posted to first real card painted, under
// 4x CPU. Measured 2026-11-11 (15 runs, one worker, a machine that was busy with other jobs): 18 to
// 54 ms. The ceiling is about five times the worst run, so the suite stays green while other jobs
// run beside it, and the regression this guards (a first render that blocks for hundreds of
// milliseconds) still fails it.
const FIRST_CARD_CEILING_MS = {
  work: 250,
  journal: 250,
  shopping: 250,
} as const;

const phone = { width: 390, height: 844 };
const hostContext = {
  locale: "en",
  theme: "light",
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
};

const tasks = [
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-000000000001",
    title: "Ring Anna om offerten",
    status: "todo",
    due_at: null,
    version: 1,
  },
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-000000000002",
    title: "Skicka faktura",
    status: "in_progress",
    due_at: null,
    version: 1,
  },
];
const workChanges = {
  card: {
    kind: "work_changes",
    items: tasks,
    total: tasks.length,
    truncated: false,
    issued_at: "2026-10-26T08:00:00Z",
  },
};

const journalDay = {
  journal_date: "2026-10-24",
  entries: [
    {
      id: "019f0000-0000-7000-8000-0000000000e1",
      source_id: "019f0000-0000-7000-8000-0000000000s1",
      journal_date: "2026-10-24",
      occurred_at: "2026-10-24T09:30:00Z",
      title: "Mötet med kunden",
      summary: "Kunden vill ha offerten före fredag.",
      key_points: [],
      project_ids: [],
      task_ids: [],
      contact_ids: [],
      archived: false,
      version: 1,
    },
  ],
  next_cursor: null,
  summary: {
    journal_date: "2026-10-24",
    exists: true,
    origin: "manual",
    status: "current",
    content: { overview: "Dagen handlade om offerten." },
  },
};

const shoppingDetail = {
  shopping_list: {
    id: "019f0000-0000-7000-8000-000000000011",
    name: "IKEA someday",
    version: 1,
    archived: false,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
  },
  items: [
    {
      id: "019f0000-0000-7000-8000-000000000012",
      list_id: "019f0000-0000-7000-8000-000000000011",
      name: "Hylla",
      quantity: "1",
      unit: null,
      store: "IKEA",
      note: null,
      recipient_contact_id: null,
      occasion: null,
      target_date: null,
      product_url: null,
      offer: null,
      offer_status: "none",
      purchased: false,
      purchased_at: null,
      version: 1,
      created_at: "2026-10-24T12:00:00Z",
      updated_at: "2026-10-24T12:00:00Z",
    },
  ],
  next_offset: null,
  evaluated_on: "2026-10-24",
};

type AppCase = {
  name: "work" | "journal" | "shopping";
  result: unknown;
  // The first real card or view, used as the end point of the time to first render: a CSS selector
  // and, where several elements match, the text the element must contain.
  firstView: { css: string; text?: string };
};

const cases: AppCase[] = [
  {
    name: "work",
    result: workChanges,
    firstView: { css: ".work-compact-card" },
  },
  {
    name: "journal",
    result: journalDay,
    firstView: { css: "h2", text: "Saturday 24 Oct" },
  },
  {
    name: "shopping",
    result: shoppingDetail,
    firstView: { css: "h1, h2, h3, h4, h5, h6", text: "IKEA someday" },
  },
];

/**
 * Watches the app's frame for the first matching element and resolves with the browser clock
 * (performance.timeOrigin + performance.now(), epoch milliseconds) of the first animation frame after
 * it is in the DOM. The host page reads the same clock when it sends the message, so the difference
 * is measured entirely inside the browser: no Playwright round trip, no Node timer.
 */
async function armFirstCardWatch(
  frame: Frame,
  firstView: AppCase["firstView"],
) {
  await frame.evaluate((view) => {
    const win = window as unknown as { __firstCardAt: Promise<number> };
    win.__firstCardAt = new Promise<number>((resolve) => {
      const matches = () =>
        Array.from(document.querySelectorAll(view.css)).some(
          (element) =>
            view.text === undefined ||
            (element.textContent ?? "").includes(view.text),
        );
      const stopWhenShown = () => {
        if (!matches()) return false;
        requestAnimationFrame(() =>
          resolve(performance.timeOrigin + performance.now()),
        );
        return true;
      };
      const observer = new MutationObserver(() => {
        if (stopWhenShown()) observer.disconnect();
      });
      observer.observe(document, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    });
  }, firstView);
}

async function measureFirstRender(page: Page, appCase: AppCase) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", {
    rate: CPU_THROTTLE_RATE,
  });
  const loadStarted = Date.now();
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp(appCase.name, "en"),
    ...phone,
    hostContext,
    replies: {},
  });
  await app.locator(SKELETON).first().waitFor();
  const skeletonMs = Date.now() - loadStarted;
  await waitForAppInitialized(page);

  const frameElement = await page.locator("iframe").elementHandle();
  const frame = await frameElement!.contentFrame();
  expect(frame).not.toBeNull();
  await armFirstCardWatch(frame!, appCase.firstView);
  const sentAt = await deliverToolResult(page, appCase.result);
  const shownAt = await frame!.evaluate(
    () =>
      (window as unknown as { __firstCardAt: Promise<number> }).__firstCardAt,
  );
  const firstCardMs = shownAt - sentAt;

  console.log(
    `simulated host perf ${appCase.name} (4x CPU): skeleton ${skeletonMs} ms (runner clock), first real card ${firstCardMs.toFixed(1)} ms (browser clock)`,
  );
  return { failures, networkRequests, firstCardMs };
}

// Timing under 4x CPU throttle: run the cases one after another, alone (see the "perf" project).
test.describe.configure({ mode: "serial" });

for (const appCase of cases) {
  test(`simulated host: ${appCase.name} shows a skeleton, then its first real card within the ceiling under 4x CPU`, async ({
    page,
  }) => {
    const { failures, networkRequests, firstCardMs } = await measureFirstRender(
      page,
      appCase,
    );
    expect(firstCardMs).toBeLessThanOrEqual(
      FIRST_CARD_CEILING_MS[appCase.name],
    );
    expect(failures).toEqual([]);
    expect(networkRequests()).toBe(0);
  });
}
