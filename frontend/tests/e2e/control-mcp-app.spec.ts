import { expect, test } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// The Control App on the SIMULATED host (see mcp-host-fixture.ts): every tool answer is a fixture,
// no backend, no database, no network. The app is Swedish by default (readBuiltApp("control")).

const phone = { width: 390, height: 844 };
const hostContext = {
  locale: "sv",
  theme: "light",
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
};
const taskId = "019f0000-0000-7000-8000-0000000000a1";
const memoryStatus = {
  settings: {
    journal: true,
    contacts: false,
    projects: false,
    tasks: false,
    paused: false,
    version: 2,
  },
  provider: "hindsight",
  sources: [
    {
      kind: "journal_entry",
      retained: 12,
      pending: 0,
      failed: 0,
      parked: 0,
      excluded: 0,
    },
  ],
};

test("Control app lists the trash and restores an item through the host on a mobile viewport", async ({
  page,
}) => {
  const trashedAt = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    ...phone,
    hostContext,
    replies: {
      restore_from_trash: {
        structuredContent: {
          kind: "task",
          id: taskId,
          label: "Skicka offert",
          trashed_at: null,
          version: 4,
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, {
    items: [
      {
        kind: "task",
        id: taskId,
        label: "Skicka offert",
        trashed_at: trashedAt,
        version: 3,
      },
    ],
    has_more: false,
  });
  await expect(app.getByText("1 borttagen · kan återställas")).toBeVisible();
  await expect(app.getByText("Skicka offert", { exact: true })).toBeVisible();
  await app.getByRole("button", { name: "Återställ Skicka offert" }).click();
  await expect(app.getByRole("status")).toHaveText(
    "Återställd: “Skicka offert”",
  );
  await expect(app.getByText("Skicka offert", { exact: true })).toHaveCount(0);
  await expect(app.getByText("Papperskorgen är tom.")).toBeVisible();
  const { calls } = await simulatedHostState(page);
  const restore = calls.find((call) => call.name === "restore_from_trash");
  expect(restore?.arguments).toMatchObject({
    kind: "task",
    record_id: taskId,
    version: 3,
  });
  expect(restore?.arguments.idempotency_key).toBeTruthy();
  // The whole app: no page error, no network request, and no horizontal overflow in the frame.
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("Control app keeps the title, the action and the tabs whole at 195 px (200 % zoom)", async ({
  page,
}) => {
  const trashedAt = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const title = "Boka tid hos tandläkaren i Uppsala";
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    width: 195,
    height: 844,
    hostContext,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, {
    items: [
      {
        kind: "task",
        id: taskId,
        label: title,
        trashed_at: trashedAt,
        version: 3,
      },
    ],
    has_more: false,
  });
  await expect(app.getByText(title, { exact: true })).toBeVisible();
  await expect(
    app.getByRole("button", { name: `Återställ ${title}` }),
  ).toBeVisible();
  // No horizontal overflow in the frame, and no tab label cut off: each label is as wide as its text.
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  const clippedTabs = await app
    .locator(".sk-segmented__label")
    .evaluateAll((labels) =>
      labels
        .filter((label) => label.scrollWidth > label.clientWidth + 1)
        .map((label) => label.textContent),
    );
  expect(clippedTabs).toEqual([]);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

for (const width of [320, 190]) {
  test(`Control app shows every tab label whole at ${width} px, with no ellipsis, and wraps the tabs instead of scrolling the row`, async ({
    page,
  }) => {
    const trashedAt = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const { app, failures, networkRequests } = await openSimulatedApp(page, {
      resource: readBuiltApp("control"),
      width,
      height: 844,
      hostContext,
      replies: {},
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, {
      items: [
        {
          kind: "task",
          id: taskId,
          label: "Skicka offert",
          trashed_at: trashedAt,
          version: 3,
        },
      ],
      has_more: false,
    });
    await expect(
      app.getByRole("button", { name: "Borttaget", exact: true }),
    ).toBeVisible();
    await expect(
      app.getByRole("button", { name: "Historik", exact: true }),
    ).toBeVisible();
    await expect(
      app.getByRole("button", { name: "Sidekicks minne", exact: true }),
    ).toBeVisible();
    // No tab text is replaced by an ellipsis (a CSS ellipsis is not in textContent, so the style is checked too),
    // and no label is cut or broken: each label is as wide as its text and one line high.
    const groups = await app
      .locator(".sk-segmented")
      .evaluateAll((segments) =>
        segments.map((segment) => segment.textContent ?? ""),
      );
    expect(groups.join("")).not.toContain("…");
    const ellipsed = await app
      .locator(".sk-segmented__label")
      .evaluateAll((labels) =>
        labels
          .filter(
            (label) => getComputedStyle(label).textOverflow === "ellipsis",
          )
          .map((label) => label.textContent),
      );
    expect(ellipsed).toEqual([]);
    const labelFit = await app
      .locator(".sk-segmented__label")
      .evaluateAll((labels) =>
        labels
          .filter((label) => {
            const style = getComputedStyle(label);
            return (
              label.scrollWidth > label.clientWidth + 1 ||
              label.getBoundingClientRect().height >
                parseFloat(style.fontSize) * 1.5
            );
          })
          .map((label) => label.textContent),
      );
    expect(labelFit).toEqual([]);
    // No tab is cut inside its own box, and the row does not scroll sideways: the tabs wrap onto more rows.
    const clipped = await app
      .locator(".sk-segmented__option")
      .evaluateAll((elements) =>
        elements
          .filter(
            (element) =>
              element.scrollWidth > element.clientWidth + 1 ||
              element.scrollHeight > element.clientHeight + 1,
          )
          .map((element) => element.textContent),
      );
    expect(clipped).toEqual([]);
    // No horizontal overflow in the frame: the page does not scroll sideways.
    const dimensions = await app.locator("body").evaluate((body) => ({
      width: body.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
    const rowScrolls = await app
      .locator(".sk-segmented")
      .evaluateAll((rows) =>
        rows.some((row) => row.scrollWidth > row.clientWidth + 1),
      );
    expect(rowScrolls).toBe(false);
    // Every tab is reachable without scrolling: each one sits whole inside the frame.
    const tabs = app.locator(".sk-segmented__option");
    await expect(tabs).toHaveCount(3);
    for (let index = 0; index < 3; index++) {
      const tab = tabs.nth(index);
      await expect(tab).toBeInViewport();
    }
    expect(failures).toEqual([]);
    expect(networkRequests()).toBe(0);
  });
}

test("Control app asks before memory is turned off and deletes only after the owner confirms", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    ...phone,
    hostContext,
    replies: {
      // The same answer for every call: the host asks for confirmation, which is what the
      // owner's switch press must lead to. A confirmed call gets this answer again.
      set_memory_settings: {
        structuredContent: {
          status: "needs_confirmation",
          settings: memoryStatus.settings,
          turning_off: [{ domain: "journal", documents: 12 }],
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, memoryStatus);
  await expect(
    app.getByRole("heading", { name: "Minnet är på" }),
  ).toBeVisible();
  // A real provider shows no test-service note.
  await expect(app.getByText(/Testminne/)).toHaveCount(0);

  const memoryCalls = async () =>
    (await simulatedHostState(page)).calls.filter(
      (call) => call.name === "set_memory_settings",
    );
  const dialog = app.getByRole("group", { name: "Slå av dagboken?" });
  const journalSwitch = app.getByRole("switch", { name: "Dagbok: på" });

  // The first press asks the host without confirm; the host answers with what would be deleted.
  await journalSwitch.click();
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "Bara Sidekicks minne av dagboken raderas (12 poster)",
  );
  expect(await memoryCalls()).toEqual([
    {
      name: "set_memory_settings",
      arguments: { expected_version: 2, journal: false },
    },
  ]);

  // Cancel closes the question and sends nothing.
  await app.getByRole("button", { name: "Avbryt" }).click();
  await expect(dialog).toHaveCount(0);
  expect(await memoryCalls()).toHaveLength(1);

  // A new press asks the host again, still without confirm.
  await journalSwitch.click();
  await expect(dialog).toBeVisible();
  await expect.poll(async () => (await memoryCalls()).length).toBe(2);
  expect((await memoryCalls())[1]).toEqual({
    name: "set_memory_settings",
    arguments: { expected_version: 2, journal: false },
  });

  // Only the explicit "Ja, radera minnet av dagboken" sends the confirmed call.
  await app
    .getByRole("button", { name: "Ja, radera minnet av dagboken" })
    .click();
  await expect.poll(async () => (await memoryCalls()).length).toBe(3);
  expect((await memoryCalls())[2]).toEqual({
    name: "set_memory_settings",
    arguments: { expected_version: 2, journal: false, confirm: true },
  });

  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("Control app has three views, History in the middle, one row at 390 px", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    ...phone,
    hostContext,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { items: [], has_more: false });
  const tabs = app.locator(".sk-segmented__option");
  await expect(tabs).toHaveCount(3);
  await expect(app.locator(".sk-segmented__label")).toHaveText([
    "Borttaget",
    "Historik",
    "Sidekicks minne",
  ]);
  // At 390 px all three tabs sit on one row and inside the frame.
  const layout = await tabs.evaluateAll((buttons) => ({
    tops: new Set(buttons.map((b) => Math.round(b.getBoundingClientRect().top)))
      .size,
    fits: buttons.every(
      (b) => b.getBoundingClientRect().right <= window.innerWidth + 1,
    ),
  }));
  expect(layout).toEqual({ tops: 1, fits: true });
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("Control app wraps its three tabs at 195 px without clipping any label", async ({
  page,
}) => {
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    width: 195,
    height: 844,
    hostContext,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { items: [], has_more: false });
  const tabs = app.locator(".sk-segmented__option");
  await expect(tabs).toHaveCount(3);
  const layout = await tabs.evaluateAll((buttons) => ({
    tops: new Set(buttons.map((b) => Math.round(b.getBoundingClientRect().top)))
      .size,
    fits: buttons.every(
      (b) => b.getBoundingClientRect().right <= window.innerWidth + 1,
    ),
  }));
  expect(layout.tops).toBeGreaterThan(1);
  expect(layout.fits).toBe(true);
  const clippedTabs = await app
    .locator(".sk-segmented__label")
    .evaluateAll((labels) =>
      labels
        .filter((label) => label.scrollWidth > label.clientWidth + 1)
        .map((label) => label.textContent),
    );
  expect(clippedTabs).toEqual([]);
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("Control app shows the assistant's activity in History, read-only, from list_assistant_activity", async ({
  page,
}) => {
  const occurredAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    ...phone,
    hostContext,
    replies: {
      list_assistant_activity: {
        structuredContent: {
          items: [
            {
              id: "019f0000-0000-7000-8000-000000000201",
              domain_event_id: "019f0000-0000-7000-8000-000000000202",
              category: "task_maintenance",
              source: "assistant",
              operation: "update_task",
              state: "applied",
              aggregate_type: "task",
              aggregate_id: taskId,
              summary: "Flyttade Förbered pitchen till Klar",
              before_values: {},
              after_values: {},
              evidence: {},
              policy_mode: null,
              correlation_id: null,
              occurred_at: occurredAt,
            },
          ],
          next_cursor: null,
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { items: [], has_more: false });
  await app.getByRole("button", { name: "Historik", exact: true }).click();
  // History is one list (changes and activity together), named "Historik".
  await expect(app.getByRole("list", { name: "Historik" })).toBeVisible();
  await expect(
    app.getByText("Flyttade Förbered pitchen till Klar", { exact: true }),
  ).toBeVisible();
  await expect(app.getByText(/^Claude · /)).toBeVisible();
  // "applied" is the normal case and is not named in the row any more.
  await expect(app.getByText(/tillämpad/)).toHaveCount(0);
  // The card only reads: no button inside the activity list.
  await expect(
    app.getByRole("list", { name: "Historik" }).getByRole("button"),
  ).toHaveCount(0);
  const { calls } = await simulatedHostState(page);
  const activity = calls.filter(
    (call) => call.name === "list_assistant_activity",
  );
  expect(activity).toEqual([
    { name: "list_assistant_activity", arguments: { limit: 25 } },
  ]);
  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});

test("Control app searches memory on Enter and on Sök in a sandbox without allow-forms", async ({
  page,
}) => {
  // The simulated host's iframe has sandbox="allow-scripts" only, so a form here never submits. The search
  // must act on the field's Enter and the button's click instead. Simulated host, not real Claude.
  const { app, failures, networkRequests } = await openSimulatedApp(page, {
    resource: readBuiltApp("control"),
    ...phone,
    // The search is part of the full view only; the inline card stays one phone screen.
    hostContext: { ...hostContext, displayMode: "fullscreen" },
    replies: {
      recall_memory: {
        structuredContent: { status: "ok", facts: [], truncated: false },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, memoryStatus);
  const recallCalls = async () =>
    (await simulatedHostState(page)).calls.filter(
      (call) => call.name === "recall_memory",
    );
  const search = app.getByRole("search");
  const field = search.getByRole("searchbox");

  await field.fill("promenad");
  await field.press("Enter");
  await expect.poll(async () => (await recallCalls()).length).toBe(1);
  expect((await recallCalls())[0]?.arguments).toMatchObject({
    query: "promenad",
  });

  await field.fill("hund");
  await search.getByRole("button", { name: "Sök" }).click();
  await expect.poll(async () => (await recallCalls()).length).toBe(2);
  expect((await recallCalls())[1]?.arguments).toMatchObject({ query: "hund" });

  await field.fill("a");
  await field.press("Enter");
  await expect(app.getByRole("alert")).toContainText("minst två tecken");
  expect(await recallCalls()).toHaveLength(2);

  expect(failures).toEqual([]);
  expect(networkRequests()).toBe(0);
});
