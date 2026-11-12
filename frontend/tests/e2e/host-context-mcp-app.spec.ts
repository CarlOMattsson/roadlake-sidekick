import { test, expect } from "@playwright/test";
import {
  deliverToolInput,
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  setHostContext,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// Host context in the SIMULATED host (see mcp-host-fixture.ts): styles.variables, safeAreaInsets,
// theme, tool-input before tool-result, and displayMode changes. No real Claude host is involved.

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
// Overdue on any later day (the due date is in the past), so the agenda summary has records to count.
const agenda = {
  items: tasks.map((task) => ({
    ...task,
    due_at: "2026-10-27T09:00:00Z",
    agenda_group: "overdue",
  })),
  next_cursor: null,
};

const inlineContext = {
  locale: "en",
  theme: "light",
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
};

const phone = { width: 390, height: 844 };

test("simulated host: styles.variables are visible in the computed style of the root", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: {
      ...inlineContext,
      styles: { variables: { "--color-text-primary": "rgb(18, 52, 86)" } },
    },
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, workChanges);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  const variable = await app
    .locator("html")
    .evaluate((element) =>
      getComputedStyle(element).getPropertyValue("--color-text-primary").trim(),
    );
  expect(variable).toBe("rgb(18, 52, 86)");
  // The host token reaches the text colour through var(--color-text-primary) in work.css.
  await expect(
    app
      .locator(".sidekick-work")
      .evaluate((element) => getComputedStyle(element).color),
  ).resolves.toBe("rgb(18, 52, 86)");
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("simulated host: padding of the root follows safeAreaInsets on a 390x844 frame", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: {
      ...inlineContext,
      safeAreaInsets: { top: 20, right: 4, bottom: 34, left: 12 },
    },
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, workChanges);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  // An inline card sits flush with the host edge (family frame): each side is only the safe-area inset.
  const padding = await app.locator(".sidekick-work").evaluate((element) => {
    const style = getComputedStyle(element);
    return [
      style.paddingTop,
      style.paddingRight,
      style.paddingBottom,
      style.paddingLeft,
    ];
  });
  expect(padding).toEqual(["20px", "4px", "34px", "12px"]);
  // The card is the frame: a hairline and the surface colour, inside the safe area.
  const frame = await app.locator(".work-compact-card").evaluate((element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return { border: style.borderTopWidth, left: rect.left, top: rect.top };
  });
  expect(frame).toEqual({ border: "1px", left: 12, top: 20 });
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("simulated host: theme dark with a light OS sets data-theme and color-scheme dark", async ({
  page,
}) => {
  // The operating system is light; the host theme is dark. The app must follow the host theme.
  await page.emulateMedia({ colorScheme: "light" });
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: { ...inlineContext, theme: "dark" },
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, workChanges);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  const scheme = await app.locator("html").evaluate((element) => ({
    theme: element.getAttribute("data-theme"),
    colorScheme: element.style.colorScheme,
  }));
  expect(scheme).toEqual({ theme: "dark", colorScheme: "dark" });
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

// Regression guard (bug found and fixed 2026-10-26): an older CSS target made the build lower
// light-dark() to --lightningcss-* variables that nothing defined, so the dark theme never applied.
// vite.mcp-app.config.ts now sets build.cssTarget to browsers with native light-dark().
test("simulated host: theme dark with a light OS gives dark tokens", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: { ...inlineContext, theme: "dark" },
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, workChanges);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  // Without host variables the text colour is the light-dark() fallback, resolved in dark mode.
  await expect(
    app
      .locator(".sidekick-work")
      .evaluate((element) => getComputedStyle(element).color),
  ).resolves.toBe("rgb(237, 237, 237)");
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("simulated host: tool-input shows the skeleton until tool-result replaces it with the card", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: inlineContext,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolInput(page, {});
  // The awaiting skeleton is the only child of #root until the first tool result arrives.
  const skeleton = app.locator("#root > [role='status']");
  await expect(skeleton).toBeVisible();
  await expect(app.locator(".work-compact-card")).toHaveCount(0);
  await deliverToolResult(page, workChanges);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  await expect(skeleton).toHaveCount(0);
  await expect(app.getByRole("listitem")).toHaveCount(tasks.length);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("simulated host: the root background is transparent", async ({ page }) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: inlineContext,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, workChanges);
  await expect(app.locator(".work-compact-card")).toBeVisible();
  // The host surface shows through the html, body and app root.
  for (const selector of ["html", "body", ".sidekick-work"]) {
    const background = await app
      .locator(selector)
      .evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(background, selector).toBe("rgba(0, 0, 0, 0)");
  }
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("simulated host: displayMode inline to fullscreen turns the agenda summary into the tab strip", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    ...phone,
    hostContext: inlineContext,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, agenda);
  // Inline with fullscreen offered, the agenda is a summary: counts in the kicker and "Open Agenda", not the item list.
  await expect(app.locator(".work-compact-card")).toBeVisible();
  await expect(
    app.getByRole("button", { name: "Open Agenda", exact: true }),
  ).toBeVisible();
  // No "Start with" line. The title counts the overdue records and the (at most three) rows open them, not the item list.
  await expect(app.locator(".work-compact-title")).toHaveText("3 overdue");
  await expect(app.locator(".work-compact-row")).toHaveCount(3);
  await expect(app.locator(".work-agenda-row")).toHaveCount(0);
  const tabs = app.getByRole("group", { name: "Views" });
  await expect(tabs).toHaveCount(0);
  await setHostContext(page, { displayMode: "fullscreen" });
  await expect(app.locator(".work-compact-card")).toHaveCount(0);
  await expect(tabs.getByRole("button")).toHaveText([
    "Agenda",
    "Status",
    "Projects",
  ]);
  await expect(
    tabs.getByRole("button", { name: "Agenda", pressed: true }),
  ).toBeVisible();
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});
