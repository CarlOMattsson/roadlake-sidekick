import { readFileSync } from "node:fs";
import { withAppLocale } from "./mcp-host-fixture";
import { test, expect, type Page } from "@playwright/test";

const entryId = "019f0000-0000-7000-8000-0000000000e1";
const sourceId = "019f0000-0000-7000-8000-0000000000s1";

test("sandboxed Journal App moves from day to entry to original and back on a mobile viewport", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick journal" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate(
    ({ resource, entryId, sourceId }) => {
      const frame = document.querySelector("iframe")!;
      const entry = {
        id: entryId,
        source_id: sourceId,
        journal_date: "2026-10-24",
        occurred_at: "2026-10-24T09:30:00Z",
        // Injected markup in a title must render as text, never as an element.
        title:
          'Mötet <img src="https://example.org/tracker" onerror="alert(1)">',
        summary: "Kunden vill ha offerten före fredag.",
        key_points: [
          { kind: "commitment", text: "Skicka offerten på torsdag." },
        ],
        project_ids: [],
        task_ids: [],
        contact_ids: [],
        archived: false,
        version: 1,
      };
      const day = {
        journal_date: "2026-10-24",
        entries: [entry],
        next_cursor: null,
        summary: {
          journal_date: "2026-10-24",
          exists: true,
          origin: "manual",
          status: "current",
          content: { overview: "Dagen handlade om offerten." },
        },
      };
      const source = {
        id: sourceId,
        source_type: "manual_text",
        journal_date: "2026-10-24",
        occurred_at: null,
        source_recorded_at: null,
        language: "sv",
        replaces_source_id: null,
        content_fingerprint: "a".repeat(64),
        created_at: "2026-10-24T09:31:00Z",
        raw_text: "Råtext: Anna vill ha offerten före fredag.",
      };
      const state = {
        calls: [] as { name: string; arguments: Record<string, unknown> }[],
        initialized: false,
      };
      Object.assign(window, { journalTest: state });
      window.addEventListener("message", (event) => {
        if (event.source !== frame.contentWindow) return;
        const message = event.data as {
          id?: number;
          method: string;
          params: { name: string; arguments: Record<string, unknown> };
        };
        const reply = (result: object) =>
          frame.contentWindow!.postMessage(
            { jsonrpc: "2.0", id: message.id, result },
            "*",
          );
        if (message.method === "ui/initialize")
          reply({
            protocolVersion: "2026-01-26",
            hostCapabilities: {},
            hostInfo: { name: "Test host", version: "1" },
            hostContext: { locale: "en", theme: "light" },
          });
        else if (message.method === "ui/notifications/initialized") {
          state.initialized = true;
          frame.contentWindow!.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: { structuredContent: day },
            },
            "*",
          );
        } else if (message.method === "tools/call") {
          state.calls.push(message.params);
          const { name, arguments: args } = message.params;
          if (name === "get_journal_entry")
            reply({ structuredContent: { entry } });
          else if (name === "get_journal_source")
            reply({ structuredContent: { source } });
          else if (name === "get_journal_day")
            reply({
              structuredContent: {
                ...day,
                journal_date: args.journal_date,
                entries: [],
                summary: { ...day.summary, exists: false, content: null },
              },
            });
          else reply({ isError: true });
        }
      });
      frame.srcdoc = resource;
    },
    { resource: html, entryId, sourceId },
  );
  const app = page.frameLocator("iframe");
  await expect(
    app.getByRole("heading", { level: 2, name: "Saturday 24 Oct" }),
  ).toBeVisible();
  await expect(app.getByText("Dagen handlade om offerten.")).toBeVisible();
  // Inline, the day shows as its glance; Open expands the day inline (no fullscreen is offered here).
  await app.getByRole("button", { name: /^(Open|Show all)/ }).click();
  await app
    .getByRole("button", {
      name: 'Mötet <img src="https://example.org/tracker" onerror="alert(1)">',
    })
    .click();
  const entryHeading = app.getByRole("heading", { level: 2 });
  await expect(entryHeading).toBeFocused();
  await expect(app.locator("img")).toHaveCount(0);
  await expect(
    app.getByText("Commitment: Skicka offerten på torsdag."),
  ).toBeVisible();
  await app.getByRole("button", { name: "Show original" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Your original text" }),
  ).toBeVisible();
  await expect(
    app.getByText("Råtext: Anna vill ha offerten före fredag."),
  ).toBeVisible();
  await app.getByRole("button", { name: "Show summary" }).click();
  await expect(
    app.getByRole("button", { name: "Show original" }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Back" }).click();
  await app.getByRole("button", { name: "Previous week" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Saturday 17 October" }),
  ).toBeVisible();
  await expect(app.getByRole("button", { name: "Back" })).toHaveCount(0);

  const state = await page.evaluate(
    () =>
      (
        window as unknown as {
          journalTest: {
            initialized: boolean;
            calls: { name: string; arguments: Record<string, unknown> }[];
          };
        }
      ).journalTest,
  );
  expect(state.initialized).toBe(true);
  // The glance reads the day's draft count once (list_pending_journal), and the day strip reads its seven days'
  // dates (list_journal_entries); those reads are not navigation.
  const calls = state.calls.filter(
    (call) =>
      call.name !== "list_pending_journal" &&
      call.name !== "list_journal_entries",
  );
  const names = calls.map((call) => call.name);
  // Back remounts the entry frame, which reads its entry again, as Work frames do.
  expect(names).toEqual([
    "get_journal_entry",
    "get_journal_source",
    "get_journal_entry",
    "get_journal_day",
  ]);
  expect(calls[0]?.arguments).toMatchObject({
    entry_id: entryId,
    include_content: true,
  });
  expect(calls[1]?.arguments).toMatchObject({
    source_id: sourceId,
    include_content: true,
  });
  expect(calls[3]?.arguments).toMatchObject({
    journal_date: "2026-10-17",
    include_content: true,
  });
  // The inlined stylesheet must reach the App: the expanded view is the full view, and the shell frame pads it 8px above (half the frame padding over the strip).
  await expect(
    app
      .locator(".sk-frame__body")
      .evaluate((element) => getComputedStyle(element).paddingTop),
  ).resolves.toBe("8px");
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Journal App shows a pending source without a draft as plain text, no button", async ({
  page,
}) => {
  const html = readFileSync(
    "../backend/src/sidekick/mcp/apps/sidekick.html",
    "utf8",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick journal" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const pending = {
      items: [
        {
          source_id: "019f0000-0000-7000-8000-0000000000s1",
          journal_date: "2026-10-24",
          source_type: "transcript_text",
          source_created_at: "2026-10-24T09:31:00Z",
          character_count: 42,
          state: "source_saved",
          draft_id: null,
          draft_title: null,
        },
      ],
    };
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as { id?: number; method: string };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "sv-SE", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized")
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: pending },
          },
          "*",
        );
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await expect(
    app.getByRole("heading", { level: 2, name: "Väntar på granskning" }),
  ).toBeVisible();
  await expect(
    app.getByText(
      "Öppna ett utkast för att granska det. Inget sparas förrän du väljer det.",
    ),
  ).toBeVisible();
  await expect(app.getByRole("button")).toHaveCount(0);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Journal App reviews a draft: pick one link, save as entry through a conflict, then shows the entry", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick journal" sandbox="allow-scripts" style="width:360px;height:900px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const draftId = "019f0000-0000-7000-8000-0000000000d1";
    const projectId = "019f0000-0000-7000-8000-0000000000p1";
    const savedEntryId = "019f0000-0000-7000-8000-0000000000e9";
    const sourceId = "019f0000-0000-7000-8000-0000000000s1";
    const pending = {
      items: [
        {
          source_id: sourceId,
          journal_date: "2026-10-24",
          source_type: "manual_text",
          source_created_at: "2026-10-24T09:31:00Z",
          character_count: 42,
          state: "draft_pending_review",
          draft_id: draftId,
          draft_title: "Utkast om offerten",
        },
      ],
    };
    const draftBase = {
      id: draftId,
      source_id: sourceId,
      journal_date: "2026-10-24",
      state: "pending_review",
      title: "Utkast om offerten",
      summary: "Kunden vill ha offerten före fredag.",
      key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
      suggestions: {
        projects: [
          { id: projectId, rationale: "Offerten hör till projektet." },
        ],
        tasks: [],
        contacts: [],
      },
      task_proposals: [],
      task_proposal_count: 0,
      catalog: {
        projects: [{ id: projectId, label: "Projekt Offert" }],
        tasks: [],
        contacts: [],
      },
    };
    const source = {
      id: sourceId,
      source_type: "manual_text",
      journal_date: "2026-10-24",
      occurred_at: null,
      source_recorded_at: null,
      language: "sv",
      created_at: "2026-10-24T09:31:00Z",
      raw_text: "Råtext: Anna vill ha offerten före fredag.",
    };
    const entry = {
      id: savedEntryId,
      source_id: sourceId,
      journal_date: "2026-10-24",
      occurred_at: null,
      title: "Utkast om offerten",
      summary: "Kunden vill ha offerten före fredag.",
      key_points: [],
      project_ids: [projectId],
      task_ids: [],
      contact_ids: [],
      archived: false,
      version: 1,
    };
    const state = {
      calls: [] as { name: string; arguments: Record<string, unknown> }[],
    };
    Object.assign(window, { journalTest: state });
    let finalizeCalls = 0;
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as {
        id?: number;
        method: string;
        params: { name: string; arguments: Record<string, unknown> };
      };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "en", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized")
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: pending },
          },
          "*",
        );
      else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name } = message.params;
        if (name === "get_journal_draft")
          // After the conflict the draft is at version 2.
          reply({
            structuredContent: {
              draft: { ...draftBase, version: finalizeCalls > 0 ? 2 : 1 },
              source,
            },
          });
        else if (name === "finalize_journal_draft") {
          finalizeCalls++;
          if (finalizeCalls === 1)
            reply({ isError: true, structuredContent: { code: "conflict" } });
          else
            reply({
              structuredContent: {
                entry,
                created_task_ids: [],
                updated_task_ids: [],
              },
            });
        } else if (name === "get_journal_entry")
          reply({ structuredContent: { entry } });
        else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Utkast om offerten" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Utkast om offerten" }),
  ).toBeVisible();
  // Inline (one card, one screen) the section headings are replaced by closed disclosure rows.
  await expect(app.getByText(/^Råtext:/)).toHaveCount(0);
  await app.getByRole("button", { name: "Show original" }).click();
  await expect(
    app.getByText("Råtext: Anna vill ha offerten före fredag."),
  ).toBeVisible();
  // The links start closed inline; opening the row shows the suggestion.
  await app.getByRole("button", { name: /^Suggested links/ }).click();
  // A suggestion has only the Godkänn/Avslå pair; the pair is the link choice.
  const link = app
    .getByRole("group", { name: "Decision for Projekt Offert" })
    .getByRole("button", { name: "Approve" });
  await expect(link).toHaveAttribute("aria-pressed", "false");
  // The inlined stylesheet must reach the App: the link group is a rounded fieldset.
  await expect(
    app
      .locator(".journal-fieldset")
      .first()
      .evaluate((element) => getComputedStyle(element).borderTopLeftRadius),
  ).resolves.toBe("8px");
  await link.click();
  await app.getByRole("button", { name: "Save as journal entry" }).click();
  await expect(
    app.getByText(
      "This saves 1 journal entry with 1 link. It creates 0 tasks and updates 0 tasks.",
    ),
  ).toBeVisible();
  await app.getByRole("button", { name: "Yes, save entry" }).click();
  const banner = app.getByRole("alert");
  await expect(banner).toBeFocused();
  await app.getByRole("button", { name: "Reload" }).click();
  await expect(app.getByRole("alert")).toHaveCount(0);
  // The chosen link survives the reload.
  await expect(link).toHaveAttribute("aria-pressed", "true");
  await app.getByRole("button", { name: "Save as journal entry" }).click();
  await app.getByRole("button", { name: "Yes, save entry" }).click();
  await expect(
    app.getByText("Journal entry saved. 0 tasks created, 0 updated."),
  ).toBeVisible();
  await expect(
    app.getByText("Kunden vill ha offerten före fredag."),
  ).toBeVisible();

  const calls = await page.evaluate(
    () =>
      (
        window as unknown as {
          journalTest: {
            calls: { name: string; arguments: Record<string, unknown> }[];
          };
        }
      ).journalTest.calls,
  );
  const names = calls.map((call) => call.name);
  expect(names).toEqual([
    "get_journal_draft",
    "finalize_journal_draft",
    "get_journal_draft",
    "finalize_journal_draft",
    "get_journal_entry",
  ]);
  expect(calls[0]?.arguments).toMatchObject({ include_content: true });
  const [first, second] = [calls[1]!.arguments, calls[3]!.arguments];
  expect(first).toMatchObject({
    expected_version: 1,
    relation_selection: {
      project_ids: [
        {
          id: "019f0000-0000-7000-8000-0000000000p1",
          origin: "model_suggested",
        },
      ],
      task_ids: [],
      contact_ids: [],
    },
    task_proposals: [],
  });
  expect(second).toMatchObject({ expected_version: 2 });
  expect(second?.idempotency_key).not.toBe(first?.idempotency_key);
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});

test("sandboxed Journal App day strip fits seven days at 320 px and scrolls inside itself at 190 px, keeping today in view", async ({
  page,
}) => {
  // Today is 21 Oct 2026, in the week of the shown day (24 Oct), so the strip scrolls to today.
  await page.clock.setFixedTime(new Date("2026-10-21T12:00:00Z"));
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.route("**/*", (route) => route.abort());
  const day = {
    journal_date: "2026-10-24",
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: "2026-10-24",
      exists: false,
      origin: "manual",
      status: "current",
      content: null,
    },
  };
  for (const width of [320, 190]) {
    await mountJournalFrame(page, {
      width,
      height: 700,
      initial: day,
      reads: {},
    });
    const app = page.frameLocator("iframe");
    await expect(
      app.getByRole("heading", { level: 2, name: "Saturday 24 Oct" }),
    ).toBeVisible();
    // Inline, the day shows as its glance; Open expands the day inline, and the strip lives in that view.
    await app.getByRole("button", { name: /^(Open|Show all)/ }).click();
    const readStrip = () =>
      app.locator(".sk-day-strip").evaluate((root) => {
        const week = root.querySelector<HTMLElement>(".sk-day-strip-week")!;
        const list = week.getBoundingClientRect();
        const today = root.querySelector('[data-today="true"]');
        const todayBox = today?.getBoundingClientRect();
        const inList = (box: DOMRect) =>
          box.left >= list.left - 0.5 && box.right <= list.right + 0.5;
        const days = Array.from(
          root.querySelectorAll(".sk-day-strip-day"),
          (button) => button.getBoundingClientRect(),
        );
        return {
          dayCount: days.length,
          dayWidths: days.map((box) => box.width),
          dayHeights: days.map((box) => box.height),
          // The arrows stay in the title row at every width, 44x44 (a swipe steps the days too).
          navSizes: Array.from(
            document.querySelectorAll<HTMLElement>(".sk-day-strip-arrow"),
            (button) => ({
              position: getComputedStyle(button).position,
              box: button.getBoundingClientRect(),
            }),
          )
            .filter((arrow) => arrow.position !== "absolute")
            .map((arrow) => ({
              width: arrow.box.width,
              height: arrow.box.height,
            })),
          allDaysInList: days.every(inList),
          scrolls: week.scrollWidth > week.clientWidth + 1,
          todayVisible: todayBox !== undefined && inList(todayBox),
        };
      });
    // The strip scrolls to today after it renders, so the check waits for it.
    await expect.poll(async () => (await readStrip()).todayVisible).toBe(true);
    const strip = await readStrip();
    expect(strip.dayCount).toBe(7);
    // Touch height stays 44 px for the arrows (on the title row) and 56 px for the days; a day is about 39 px at 320 px and
    // at least 30 px at 190 px (the full view pads 16 px each side).
    const heights = [
      ...strip.dayHeights,
      ...strip.navSizes.map((s) => s.height),
    ];
    for (const height of heights) expect(height).toBeGreaterThanOrEqual(43.5);
    expect(strip.navSizes).toHaveLength(2);
    for (const size of strip.navSizes)
      expect(size.width).toBeGreaterThanOrEqual(43.5);
    for (const dayWidth of strip.dayWidths)
      expect(dayWidth).toBeGreaterThanOrEqual(29.5);
    if (width === 320) {
      // Seven days fit without horizontal scroll: every day is inside the strip.
      expect(strip.scrolls).toBe(false);
      expect(strip.allDaysInList).toBe(true);
    } else {
      // Narrow: the week scrolls inside the strip, and today is brought into view.
      expect(strip.scrolls).toBe(true);
    }
    const overflow = await app.locator("body").evaluate((body) => ({
      width: body.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(overflow.width).toBeLessThanOrEqual(overflow.viewport);
  }
  expect(failures).toEqual([]);
});

// The week row "‹ 29 okt–4 nov ›" with "Idag" after it (an older week) at 360 px and 200 % text
// must not be wider than its frame. "Idag" may drop to a line of its own; the arrows keep their place. A simulated host.
test("sandboxed Journal App week row with Today shown fits 360 px at 200 % text without sideways overflow", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date("2026-11-20T12:00:00Z"));
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.route("**/*", (route) => route.abort());
  const day = {
    journal_date: "2026-10-24",
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: "2026-10-24",
      exists: false,
      origin: "manual",
      status: "current",
      content: null,
    },
  };
  await mountJournalFrame(page, {
    width: 360,
    height: 800,
    initial: day,
    reads: {},
  });
  const app = page.frameLocator("iframe");
  await expect(
    app.getByRole("heading", { level: 2, name: "Saturday 24 Oct" }),
  ).toBeVisible();
  await app.getByRole("button", { name: /^(Open|Show all)/ }).click();
  await app.locator("html").evaluate((root) => {
    root.style.fontSize = "32px";
  });
  const weekrow = app.locator(".sk-day-strip-weekrow");
  await expect(weekrow).toBeVisible();
  await expect(weekrow.getByRole("button", { name: "Today" })).toBeVisible();
  const read = () =>
    weekrow.evaluate((row) => {
      const frame = document.documentElement;
      const box = row.getBoundingClientRect();
      const kids = Array.from(row.children, (child) =>
        child.getBoundingClientRect(),
      );
      return {
        rowRight: box.right,
        contentRight: frame.clientWidth,
        rowScrolls: row.scrollWidth > row.clientWidth + 0.5,
        pageScrolls: frame.scrollWidth > frame.clientWidth + 0.5,
        kidsRight: Math.max(...kids.map((kid) => kid.right)),
        arrowsLeft: [kids[0]?.left, kids[2]?.left],
      };
    });
  await expect.poll(async () => (await read()).rowScrolls).toBe(false);
  const measured = await read();
  expect(measured.pageScrolls).toBe(false);
  expect(measured.kidsRight).toBeLessThanOrEqual(measured.contentRight + 0.5);
  expect(failures).toEqual([]);
});

test("sandboxed Journal App draft decision bar is not sticky at 320 px and 190 px, and is compact above 400 px", async ({
  page,
}) => {
  const draftId = "019f0000-0000-7000-8000-0000000000d1";
  const projectId = "019f0000-0000-7000-8000-0000000000p1";
  const sourceId = "019f0000-0000-7000-8000-0000000000s1";
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.route("**/*", (route) => route.abort());
  const pending = {
    items: [
      {
        source_id: sourceId,
        journal_date: "2026-10-24",
        source_type: "manual_text",
        source_created_at: "2026-10-24T09:31:00Z",
        character_count: 42,
        state: "draft_pending_review",
        draft_id: draftId,
        draft_title: "Utkast om offerten",
      },
    ],
  };
  const draft = {
    id: draftId,
    source_id: sourceId,
    journal_date: "2026-10-24",
    state: "pending_review",
    title: "Utkast om offerten",
    summary: "Kunden vill ha offerten före fredag.",
    key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
    suggestions: {
      projects: [{ id: projectId, rationale: "Offerten hör till projektet." }],
      tasks: [],
      contacts: [],
    },
    task_proposals: [],
    task_proposal_count: 0,
    catalog: {
      projects: [{ id: projectId, label: "Projekt Offert" }],
      tasks: [],
      contacts: [],
    },
    version: 1,
  };
  const source = {
    id: sourceId,
    source_type: "manual_text",
    journal_date: "2026-10-24",
    occurred_at: null,
    source_recorded_at: null,
    language: "sv",
    created_at: "2026-10-24T09:31:00Z",
    raw_text: "Råtext: Anna vill ha offerten före fredag.",
  };
  for (const width of [320, 190, 500]) {
    await mountJournalFrame(page, {
      width,
      height: 900,
      initial: pending,
      reads: { get_journal_draft: { draft, source } },
    });
    const app = page.frameLocator("iframe");
    await app.getByRole("button", { name: "Utkast om offerten" }).click();
    await expect(
      app.getByRole("heading", { level: 2, name: "Utkast om offerten" }),
    ).toBeVisible();
    const bar = app.locator(".journal-decision-bar");
    const style = await bar.evaluate((element) => ({
      position: getComputedStyle(element).position,
      height: element.getBoundingClientRect().height,
    }));
    if (width > 400) {
      expect(style.position).toBe("sticky");
      expect(style.height).toBeLessThanOrEqual(72);
      continue;
    }
    // At 400 px and under the bar is in the flow, so it cannot cover "Show original" or the content.
    expect(style.position).toBe("static");
    const showOriginal = app.getByRole("button", { name: "Show original" });
    await showOriginal.scrollIntoViewIfNeeded();
    const hitsButton = await showOriginal.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const hit = element.ownerDocument.elementFromPoint(
        box.left + box.width / 2,
        box.top + box.height / 2,
      );
      return element.contains(hit);
    });
    expect(hitsButton).toBe(true);
    const overflow = await app.locator("body").evaluate((body) => ({
      width: body.scrollWidth,
      viewport: window.innerWidth,
    }));
    expect(overflow.width).toBeLessThanOrEqual(overflow.viewport);
  }
  expect(failures).toEqual([]);
});

/**
 * Mounts the Journal App in a sandboxed iframe of the given size. `initial` is the first tool result;
 * `reads` answers tools/call by tool name, and any other call gets an error.
 */
async function mountJournalFrame(
  page: Page,
  options: {
    width: number;
    height: number;
    initial: object;
    reads: Record<string, object>;
  },
): Promise<void> {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  await page.setContent(
    `<iframe title="Sidekick journal" sandbox="allow-scripts" style="width:${options.width}px;height:${options.height}px;border:0"></iframe>`,
  );
  await page.evaluate(
    ({ resource, initial, reads }) => {
      const frame = document.querySelector("iframe")!;
      window.addEventListener("message", (event) => {
        if (event.source !== frame.contentWindow) return;
        const message = event.data as {
          id?: number;
          method: string;
          params: { name: string };
        };
        const reply = (result: object) =>
          frame.contentWindow!.postMessage(
            { jsonrpc: "2.0", id: message.id, result },
            "*",
          );
        if (message.method === "ui/initialize")
          reply({
            protocolVersion: "2026-01-26",
            hostCapabilities: {},
            hostInfo: { name: "Test host", version: "1" },
            hostContext: { locale: "en", theme: "light" },
          });
        else if (message.method === "ui/notifications/initialized")
          frame.contentWindow!.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: { structuredContent: initial },
            },
            "*",
          );
        else if (message.method === "tools/call") {
          const name = message.params.name;
          if (name in reads) reply({ structuredContent: reads[name] });
          else reply({ isError: true });
        }
      });
      frame.srcdoc = resource;
    },
    { resource: html, initial: options.initial, reads: options.reads },
  );
}
