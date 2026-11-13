// Playwright runs this file outside Vitest: it reads the bundled app HTML (and font files) from disk to serve them to the simulated host.
import { readFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";
import {
  effectiveTargetSize,
  withAppLocale,
  type AppLocale,
} from "./mcp-host-fixture";

// The inline and fullscreen design language of the built Work and Journal Apps, in a simulated
// host (the same sandboxed iframe pattern as work-mcp-app.spec.ts and journal-mcp-app.spec.ts).
// No backend and no database: every tool answer is a fixture below.

type Call = { name: string; arguments: Record<string, unknown> };
type HostState = { initialized: boolean; calls: Call[] };
type HostConfig = {
  resource: string;
  width: number;
  height: number;
  hostContext: Record<string, unknown>;
  /** The structuredContent of the tool result that opens the app. */
  result: unknown;
  /** Answers per tool name; a tool without an answer gets isError. */
  replies: Record<string, unknown>;
};

const inlineContext = {
  locale: "en",
  theme: "light",
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
};
const fullscreenContext = {
  locale: "en",
  theme: "light",
  displayMode: "fullscreen",
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
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-000000000003",
    title: "Boka mötet",
    status: "blocked",
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
const agenda = { items: tasks, next_cursor: null };
const board = {
  columns: {
    todo: [tasks[0]],
    in_progress: [tasks[1]],
    blocked: [tasks[2]],
    completed: [],
  },
  next_cursor: null,
};
const journalEntryCard = {
  entry: {
    id: "019f0000-0000-7000-8000-0000000000e1",
    title: "Mötet med Anna",
    summary: "Kunden vill ha offerten före fredag.",
    contact_ids: [],
    task_ids: [],
  },
};

/**
 * Installs the simulated host in the page. Written as one self-contained function, because
 * Playwright serialises its source into the browser.
 */
function installHost(config: HostConfig) {
  const frame = document.querySelector("iframe")!;
  const state: HostState = { initialized: false, calls: [] };
  Object.assign(window, { mcpAppTest: state });
  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow) return;
    const message = event.data as {
      id?: number;
      method: string;
      params: Call;
    };
    const post = (body: object) =>
      frame.contentWindow!.postMessage({ jsonrpc: "2.0", ...body }, "*");
    if (message.method === "ui/initialize")
      post({
        id: message.id,
        result: {
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: config.hostContext,
        },
      });
    else if (message.method === "ui/notifications/initialized") {
      state.initialized = true;
      post({
        method: "ui/notifications/tool-result",
        params: { structuredContent: config.result },
      });
    } else if (message.method === "tools/call") {
      state.calls.push(message.params);
      const answer = config.replies[message.params.name];
      post({ id: message.id, result: answer ?? { isError: true } });
    }
  });
  frame.srcdoc = config.resource;
}

/** Opens one app in a sized iframe, with all network requests aborted and page errors collected. */
async function openApp(page: Page, config: HostConfig) {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setViewportSize({ width: config.width, height: config.height });
  // The outer page has no body margin, so the iframe alone decides its width.
  await page.setContent(
    `<style>html,body{margin:0}</style><iframe title="Sidekick" sandbox="allow-scripts" style="display:block;width:${config.width}px;height:${config.height}px;border:0"></iframe>`,
  );
  await page.evaluate(installHost, config);
  return {
    app: page.frameLocator("iframe"),
    failures,
    networkRequests: () => networkRequests,
  };
}

async function hostState(page: Page) {
  return page.evaluate(
    () => (window as unknown as { mcpAppTest: HostState }).mcpAppTest,
  );
}

/**
 * The built app with the Sidekick app locale declared. The host's locale is not an input: these
 * specs send en-US or en hosts, and the language still comes from the declared Sidekick setting.
 */
function readResource(_room: "work" | "journal", locale: AppLocale = "en") {
  return withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    locale,
  );
}

test("inline work_changes card on a 390x844 frame has no internal scroll", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work"),
    width: 390,
    height: 844,
    hostContext: inlineContext,
    result: workChanges,
    replies: {},
  });
  const card = app.locator(".work-compact-card");
  await expect(card).toBeVisible();
  await expect(card.getByRole("listitem")).toHaveCount(tasks.length);
  const fit = await card.evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }));
  expect(fit.scrollHeight).toBeLessThanOrEqual(fit.clientHeight + 1);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("inline journal entry card on a 390x844 frame has no internal scroll and at most two actions", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("journal"),
    width: 390,
    height: 844,
    hostContext: inlineContext,
    result: journalEntryCard,
    replies: {},
  });
  const card = app.locator("section.sidekick-journal");
  await expect(card.getByRole("heading", { level: 2 })).toHaveText(
    journalEntryCard.entry.title,
  );
  const fit = await card.evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }));
  expect(fit.scrollHeight).toBeLessThanOrEqual(fit.clientHeight + 1);
  expect(await card.getByRole("button").count()).toBeLessThanOrEqual(2);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

// The inline work_changes card is a compact list plus "Open"; status
// changes are made in fullscreen only, so the inline card has at most two action buttons.
test("inline work_changes card shows at most two action buttons", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work"),
    width: 390,
    height: 844,
    hostContext: inlineContext,
    result: workChanges,
    replies: {},
  });
  const card = app.locator(".work-compact-card");
  await expect(card).toBeVisible();
  expect(await card.getByRole("button").count()).toBeLessThanOrEqual(2);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("fullscreen 1280x800 shows the three-tab strip with Agenda selected and Board reads get_work_board", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work"),
    width: 1280,
    height: 800,
    hostContext: fullscreenContext,
    result: agenda,
    replies: { get_work_board: { structuredContent: board } },
  });
  const tabs = app.getByRole("group", { name: "Views" });
  await expect(tabs.getByRole("button")).toHaveText([
    "Agenda",
    "Status",
    "Projects",
  ]);
  await expect(
    tabs.getByRole("button", { name: "Agenda", pressed: true }),
  ).toBeVisible();
  await tabs.getByRole("button", { name: "Status" }).click();
  await expect(
    tabs.getByRole("button", { name: "Status", pressed: true }),
  ).toBeVisible();
  await expect(app.getByRole("region", { name: "To do" })).toBeVisible();
  const state = await hostState(page);
  expect(state.initialized).toBe(true);
  // The To sort row above the agenda reads the unsorted count once when the app opens, and the tag
  // filter reads the tag list once; the Board read follows the Board press. Each read is listed, so
  // no other call goes unnoticed.
  expect(state.calls.map((call) => call.name)).toEqual([
    "list_tags",
    "list_tasks",
    "get_work_board",
  ]);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("fullscreen 390x844 shows the tab strip and has no horizontal scroll", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work"),
    width: 390,
    height: 844,
    hostContext: fullscreenContext,
    result: agenda,
    replies: {},
  });
  const tabs = app.getByRole("group", { name: "Views" });
  await expect(tabs.getByRole("button")).toHaveText([
    "Agenda",
    "Status",
    "Projects",
  ]);
  await expect(tabs.getByRole("button", { name: "Agenda" })).toBeVisible();
  const frameScroll = await app.locator("html").evaluate((element) => ({
    scrollWidth: element.ownerDocument.documentElement.scrollWidth,
    innerWidth: element.ownerDocument.defaultView?.innerWidth ?? 0,
  }));
  expect(frameScroll.scrollWidth).toBeLessThanOrEqual(frameScroll.innerWidth);
  const pageScroll = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(pageScroll.scrollWidth).toBeLessThanOrEqual(pageScroll.innerWidth);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("inline work_changes card buttons are at least 44 px high on a 390x844 frame", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work"),
    width: 390,
    height: 844,
    hostContext: inlineContext,
    result: workChanges,
    replies: {},
  });
  const card = app.locator(".work-compact-card");
  await expect(card).toBeVisible();
  const buttons = await card.getByRole("button").all();
  expect(buttons.length).toBeGreaterThan(0);
  for (const button of buttons) {
    // Effective hit area: compact buttons are 40 visible with a 48 px ::after hit area.
    const box = await effectiveTargetSize(button);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("inline journal entry card button is at least 44 px high on a 390x844 frame", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("journal"),
    width: 390,
    height: 844,
    hostContext: inlineContext,
    result: journalEntryCard,
    replies: {},
  });
  const card = app.locator("section.sidekick-journal");
  await expect(card).toBeVisible();
  const buttons = await card.getByRole("button").all();
  expect(buttons.length).toBeGreaterThan(0);
  for (const button of buttons) {
    const box = await button.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("fullscreen 390x844 view tabs are 44 px high, the touch target itself", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work"),
    width: 390,
    height: 844,
    hostContext: fullscreenContext,
    result: agenda,
    replies: {},
  });
  const tabs = app.getByRole("group", { name: "Views" });
  await expect(tabs.getByRole("button")).toHaveCount(3);
  const buttons = await tabs.getByRole("button").all();
  // Designsystem §3 "Flikar": the tab is 44 px high, so the box is the touch target; a tap just inside its top
  // and bottom edges lands on the tab.
  for (const button of buttons) {
    const box = await button.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    const hits = await button.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const top = document.elementFromPoint(x, rect.top + 1);
      const bottom = document.elementFromPoint(x, rect.bottom - 1);
      return [element.contains(top), element.contains(bottom)];
    });
    expect(hits).toEqual([true, true]);
  }
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("the Sidekick app locale decides the language: an en-US host with the setting sv gets Swedish", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work", "sv"),
    width: 1280,
    height: 800,
    hostContext: { ...fullscreenContext, locale: "en-US" },
    result: agenda,
    replies: {},
  });
  await expect(app.locator("#root")).toHaveAttribute("lang", "sv");
  const tabs = app.getByRole("group", { name: "Vyer" });
  await expect(tabs.getByRole("button", { name: "Projekt" })).toBeVisible();
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("the Sidekick app locale decides the language: an sv-SE host with the setting en gets English", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openApp(page, {
    resource: readResource("work", "en"),
    width: 1280,
    height: 800,
    hostContext: { ...fullscreenContext, locale: "sv-SE" },
    result: agenda,
    replies: {},
  });
  await expect(app.locator("#root")).toHaveAttribute("lang", "en");
  const tabs = app.getByRole("group", { name: "Views" });
  await expect(tabs.getByRole("button", { name: "Projects" })).toBeVisible();
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});
