import { expect, test } from "@playwright/test";
import type { FrameLocator, Locator, Page } from "@playwright/test";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  simulatedHostState,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// SIMULATED HOST (see mcp-host-fixture.ts). Not a real Claude or Sidekick host: every tool answer
// and every host message is a fixture. Covers the mobile accessibility baseline of the inline
// MCP App surfaces at 320 and 390 px: no horizontal scroll, 44 px touch targets, keyboard reach
// with Tab, Enter and Space, and a visible focus ring.

const MIN_TARGET_PX = 44;
/** Upper bound on Tab presses before a target counts as unreachable by keyboard. */
const MAX_TABS = 12;
const viewports = [
  { width: 320, height: 640 },
  { width: 390, height: 844 },
];

const inlineContext = {
  locale: "en",
  theme: "light",
  displayMode: "inline",
  availableDisplayModes: ["inline", "fullscreen"],
};

const ringAnna = {
  kind: "task",
  id: "019f0000-0000-7000-8000-000000000001",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: "2026-10-27T09:00:00Z",
  version: 1,
};
const sendInvoice = {
  kind: "task",
  id: "019f0000-0000-7000-8000-000000000002",
  title: "Skicka faktura",
  status: "in_progress",
  due_at: null,
  version: 1,
};
const bookMeeting = {
  kind: "task",
  id: "019f0000-0000-7000-8000-000000000003",
  title: "Boka mötet",
  status: "blocked",
  due_at: "2026-10-28T09:00:00Z",
  version: 1,
};
const tasks = [ringAnna, sendInvoice, bookMeeting];
const workChanges = {
  card: {
    kind: "work_changes",
    items: tasks,
    total: tasks.length,
    truncated: false,
    issued_at: "2026-10-26T08:00:00Z",
  },
};
const board = {
  columns: {
    todo: [ringAnna],
    in_progress: [sendInvoice],
    blocked: [bookMeeting],
    completed: [],
  },
  next_cursor: null,
};
const contactIds = {
  anna: "019f0000-0000-7000-8000-000000000011",
  bo: "019f0000-0000-7000-8000-000000000012",
};
const contacts = {
  contacts: [
    { id: contactIds.anna, display_name: "Anna Andersson", archived: false },
    { id: contactIds.bo, display_name: "Bo Berg", archived: false },
  ],
  next_cursor: null,
  q: "",
  include_archived: false,
};
// A host without fullscreen (a mobile host) gets the whole Contact list inline, not the summary.
const inlineOnlyContext = {
  ...inlineContext,
  availableDisplayModes: ["inline"],
};
const asaId = "019f0000-0000-7000-8000-000000000013";
// Three sections: A, B and Å, the last one checks the Swedish order of the letters.
const fullContacts = {
  contacts: [
    ...contacts.contacts,
    { id: asaId, display_name: "Åsa Lind", archived: false },
  ],
  next_cursor: null,
  q: "",
  include_archived: false,
};
const annaRecord = {
  id: contactIds.anna,
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};
const entryId = "019f0000-0000-7000-8000-0000000000e1";
const journalCard = {
  entry: {
    id: entryId,
    title: "Mötet med Anna",
    summary: "Kunden vill ha offerten före fredag.",
    contact_ids: [contactIds.anna],
    task_ids: [ringAnna.id],
  },
};
const journalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-26",
  occurred_at: "2026-10-26T09:30:00Z",
  title: "Mötet med Anna",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [{ kind: "commitment", text: "Skicka offerten på torsdag." }],
  project_ids: [],
  task_ids: [ringAnna.id],
  contact_ids: [contactIds.anna],
  archived: false,
  version: 1,
};

type Effect =
  | { kind: "fullscreen" }
  | { kind: "tool"; name: string; argument: [string, string] };
type Surface = {
  name: string;
  resource: "work" | "journal";
  structuredContent: unknown;
  /** Host context for this surface; the inline context with fullscreen offered when absent. */
  hostContext?: Record<string, unknown>;
  replies?: Record<string, unknown>;
  /**
   * The summary's Open, pressed once the result is shown. A host without fullscreen gets the summary
   * first, and Show all expands the full view inline; the checks then run on the expanded view.
   */
  openSummary?: (app: FrameLocator) => Locator;
  /** Visible once the result is shown (and after openSummary, when given). */
  ready: (app: FrameLocator) => Locator;
  /** The action the keyboard test reaches with Tab and activates. */
  target: (app: FrameLocator) => Locator;
  effect: Effect;
};

// Inline-only host: the Contact list is a summary with Show all, and Show all expands the full list inline
// (section letters and one row per Contact). No fullscreen is requested.
const inlineOnlyContactList: Surface = {
  name: "contact list inline-only host",
  resource: "work",
  structuredContent: fullContacts,
  hostContext: inlineOnlyContext,
  openSummary: (app) =>
    app.getByRole("button", { name: "Show all", exact: true }),
  replies: {
    get_contact_context: {
      structuredContent: {
        contact: annaRecord,
        projects: { items: [], next_cursor: null },
        tasks: { items: [], next_cursor: null },
      },
    },
  },
  ready: (app) => app.getByRole("list", { name: "Contacts" }),
  target: (app) =>
    app.getByRole("button", { name: "Anna Andersson", exact: true }),
  effect: {
    kind: "tool",
    name: "get_contact_context",
    argument: ["contact_id", contactIds.anna],
  },
};

const surfaces: Surface[] = [
  {
    name: "work_changes card",
    resource: "work",
    structuredContent: workChanges,
    ready: (app) => app.locator(".work-compact-card"),
    target: (app) =>
      app.getByRole("button", { name: "Show all (3)", exact: true }),
    effect: { kind: "fullscreen" },
  },
  {
    name: "board summary",
    resource: "work",
    structuredContent: board,
    ready: (app) => app.getByRole("button", { name: /^Open Status/ }),
    target: (app) => app.getByRole("button", { name: /^Open Status/ }),
    effect: { kind: "fullscreen" },
  },
  {
    // Inline with fullscreen offered, the Contact list is a summary (count and "Show all"), not the list.
    // The inline context lists fullscreen in availableDisplayModes, so this is the variant that ships.
    name: "contact list summary",
    resource: "work",
    structuredContent: contacts,
    ready: (app) => app.locator(".work-compact-card"),
    target: (app) => app.getByRole("button", { name: "Show all", exact: true }),
    effect: { kind: "fullscreen" },
  },
  {
    name: "journal entry card",
    resource: "journal",
    structuredContent: journalCard,
    replies: {
      get_journal_entry: { structuredContent: { entry: journalEntry } },
    },
    ready: (app) =>
      app.getByRole("button", { name: "Open entry", exact: true }),
    target: (app) =>
      app.getByRole("button", { name: "Open entry", exact: true }),
    effect: {
      kind: "tool",
      name: "get_journal_entry",
      argument: ["entry_id", entryId],
    },
  },
  inlineOnlyContactList,
];

/** Opens a surface inline at one width on the simulated host and delivers its result. */
async function openSurface(
  page: Page,
  surface: Surface,
  viewport: { width: number; height: number },
) {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp(surface.resource, "en"),
    ...viewport,
    hostContext: surface.hostContext ?? inlineContext,
    replies: surface.replies ?? {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, surface.structuredContent);
  if (surface.openSummary) await surface.openSummary(opened.app).click();
  await expect(surface.ready(opened.app)).toBeVisible();
  return opened;
}

/** Fails with the offending element names; each name shows the measured size. */
async function smallTargets(app: FrameLocator): Promise<string[]> {
  const offenders: string[] = [];
  for (const button of await app.getByRole("button").all()) {
    if (!(await button.isVisible())) continue;
    const name = ((await button.textContent()) ?? "").trim() || "(unnamed)";
    // The effective hit area: the box plus an absolutely positioned ::after (compact 40 visible / 48 hit).
    const box = await effectiveTargetSize(button);
    if (!box || box.width < MIN_TARGET_PX || box.height < MIN_TARGET_PX)
      offenders.push(
        `${name}: ${box ? `${Math.round(box.width)}x${Math.round(box.height)}` : "no box"}`,
      );
  }
  return offenders;
}

async function expectNoHorizontalScroll(app: FrameLocator) {
  for (const selector of ["html", "body"]) {
    const widths = await app.locator(selector).evaluate((element) => ({
      scroll: element.scrollWidth,
      client: element.clientWidth,
    }));
    expect(widths.scroll, selector).toBeLessThanOrEqual(widths.client);
  }
}

/** Presses Tab until the target has focus. The focus must come from the keyboard, not a click. */
async function tabTo(page: Page, target: Locator) {
  for (let presses = 0; presses < MAX_TABS; presses++) {
    if (await target.evaluate((el) => el.ownerDocument.activeElement === el))
      return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`Tab did not reach the target within ${MAX_TABS} presses`);
}

/** A visible ring: an outline that is not none (with a width) or any box-shadow on the focused element. */
async function expectVisibleFocusRing(target: Locator) {
  const ring = await target.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    };
  });
  const outlined = ring.outlineStyle !== "none" && ring.outlineWidth !== "0px";
  const shadowed = ring.boxShadow !== "none";
  expect(outlined || shadowed, JSON.stringify(ring)).toBe(true);
}

for (const viewport of viewports) {
  test.describe(`${viewport.width} px`, () => {
    for (const surface of surfaces) {
      test(`simulated host: ${surface.name} at ${viewport.width} px has no horizontal scroll and 44 px targets`, async ({
        page,
      }) => {
        const { app, failures, networkRequests } = await openSurface(
          page,
          surface,
          viewport,
        );
        await expectNoHorizontalScroll(app);
        expect(await smallTargets(app)).toEqual([]);
        expect(failures).toEqual([]);
        expect(networkRequests()).toBe(0);
      });

      for (const key of ["Enter", "Space"] as const) {
        test(`simulated host: ${surface.name} at ${viewport.width} px is reached by Tab and activated by ${key}`, async ({
          page,
        }) => {
          const { app, failures, networkRequests } = await openSurface(
            page,
            surface,
            viewport,
          );
          await page.locator("iframe").focus();
          const target = surface.target(app);
          await tabTo(page, target);
          await expect(target).toBeFocused();
          await expectVisibleFocusRing(target);

          await page.keyboard.press(key);
          if (surface.effect.kind === "fullscreen") {
            await expect
              .poll(
                async () =>
                  (await simulatedHostState(page)).displayModeRequests,
              )
              .toEqual(["fullscreen"]);
          } else {
            const { name, argument } = surface.effect;
            const [argKey, argValue] = argument;
            // The app reads the record itself: the tools/call must carry the id of the shown record.
            await expect
              .poll(
                async () =>
                  (await simulatedHostState(page)).calls.find(
                    (call) => call.name === name,
                  )?.arguments[argKey],
              )
              .toBe(argValue);
          }
          expect(failures).toEqual([]);
          expect(networkRequests()).toBe(0);
        });
      }
    }

    test(`simulated host: inline-only Contact list at ${viewport.width} px shows every row`, async ({
      page,
    }) => {
      const { app, failures, networkRequests } = await openSurface(
        page,
        inlineOnlyContactList,
        viewport,
      );
      // Show all has expanded the full list inline: no summary Show all is left, and no fullscreen was asked for.
      await expect(
        app.getByRole("button", { name: "Show all", exact: true }),
      ).toHaveCount(0);
      expect((await simulatedHostState(page)).displayModeRequests).toEqual([]);
      // With 15 Contacts or fewer the list has no letter headings (LETTER_HEADINGS_ABOVE in contacts-list.tsx).
      for (const letter of ["A", "B", "Å"])
        await expect(
          app.getByRole("heading", { level: 3, name: letter, exact: true }),
        ).toHaveCount(0);
      for (const contact of fullContacts.contacts)
        await expect(
          app.getByRole("button", { name: contact.display_name, exact: true }),
        ).toBeVisible();
      expect(failures).toEqual([]);
      expect(networkRequests()).toBe(0);
    });
  });
}
