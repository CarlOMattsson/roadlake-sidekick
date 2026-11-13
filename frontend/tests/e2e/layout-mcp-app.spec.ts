import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import { domainReplies, opening } from "./sidekick-domain-fixtures";

// Layout measured in a real Chromium instead of read out of the stylesheets: the sizes of the touch targets, the row
// menu's x and date input, the profile line's single line, and where the chevron goes at large text. Simulated host
// (see mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture.

const uid = (n: number) =>
  `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`;
const DAY_MS = 24 * 60 * 60 * 1000;
/** A target is 48 px for a finger: 40 drawn plus 4 on each side, or the chip's 32 plus 8 on each. */
const TARGET_PX = 48;

const fullscreen = {
  locale: "sv",
  theme: "light",
  displayMode: "fullscreen",
  availableDisplayModes: ["inline", "fullscreen"],
};
const inline = { ...fullscreen, locale: "en", displayMode: "inline" };

const overdueTask = {
  kind: "task",
  id: uid(1),
  title: "Skicka faktura till Bergström Bygg AB för oktober",
  status: "todo",
  priority: "high",
  due_at: new Date(Date.now() - DAY_MS).toISOString(),
  project_id: null,
  project_title: "Bokslut 2026 och årsredovisning",
  domain_accent: "blue",
  agenda_group: "overdue",
  version: 1,
};
const agenda = { items: [overdueTask], next_cursor: null };

type Box = { x: number; y: number; width: number; height: number };
async function boxOf(locator: Locator): Promise<Box> {
  const box = await locator.boundingBox();
  expect(box, "the element has a box").not.toBeNull();
  return box as Box;
}

async function openAgenda(page: Page) {
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 800,
    hostContext: fullscreen,
    replies: { get_work_agenda: { structuredContent: agenda } },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, agenda);
  return opened;
}

async function openRowMenu(row: Locator) {
  await row
    .locator(".work-agenda-body > button")
    .dispatchEvent("contextmenu", undefined, { timeout: 8000 });
  await expect(row.locator(".work-agenda-menu")).toBeVisible();
}

test("Agenda: the view tabs and the row line hold 48 px, the row menu's x is a 48 x 48 square over the chevron's box", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const viewTabs = app.locator(".work-view-tabs__tab");
  expect(await viewTabs.count()).toBeGreaterThan(1);
  for (const tab of await viewTabs.all())
    expect((await effectiveTargetSize(tab))?.height).toBeGreaterThanOrEqual(
      TARGET_PX,
    );
  const row = app.locator(".work-agenda-row").first();
  expect(
    (await boxOf(row.locator(".work-agenda-line"))).height,
  ).toBeGreaterThanOrEqual(TARGET_PX);
  const chevron = row.locator(".work-open-chevron");
  const chevronBox = await boxOf(chevron);
  await openRowMenu(row);
  const close = row.locator(".work-agenda-menu-close");
  const closeBox = await boxOf(close);
  expect(closeBox.width).toBe(TARGET_PX);
  expect(closeBox.height).toBe(TARGET_PX);
  // The chevron gives way to the x but keeps its box, so the title keeps its width; the x lies in the same column.
  await expect(chevron).toHaveCSS("visibility", "hidden");
  const keptBox = await boxOf(chevron);
  expect([keptBox.x, keptBox.width]).toEqual([chevronBox.x, chevronBox.width]);
  const centre = chevronBox.x + chevronBox.width / 2;
  expect(centre).toBeGreaterThanOrEqual(closeBox.x);
  expect(centre).toBeLessThanOrEqual(closeBox.x + closeBox.width);
  // The box is the target: no pseudo-element of its own.
  expect(await effectiveTargetSize(close)).toEqual({
    width: TARGET_PX,
    height: TARGET_PX,
  });
  expect(failures).toEqual([]);
});

test("Agenda row menu at 200 % text: no chip breaks inside its label, and the date input lies over its chip with the 48 target whole", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  await app.locator("html").evaluate((root) => {
    root.style.fontSize = "32px";
  });
  const row = app.locator(".work-agenda-row").first();
  await openRowMenu(row);
  const chips = row.locator(".work-agenda-choices > .sk-chip");
  expect(await chips.count()).toBeGreaterThan(0);
  for (const chip of await chips.all()) {
    // A label on one line: the chip is not taller than the one-line floor with its air (56) plus the 1 px edges.
    expect(
      (await boxOf(chip)).height,
      await chip.innerText(),
    ).toBeLessThanOrEqual(58);
  }
  await row.getByRole("button", { name: /^Datum/ }).click();
  const input = row.getByLabel("Välj datum", { exact: true });
  const chip = row.locator(".work-agenda-date-chip");
  const inputBox = await boxOf(input);
  const chipBox = await boxOf(chip);
  // At least the chip's own box and its 1 px edge, then 3 px more on every side (inset -4 from the padding box).
  expect(inputBox.x).toBeLessThanOrEqual(chipBox.x - 3 + 0.5);
  expect(inputBox.y).toBeLessThanOrEqual(chipBox.y - 3 + 0.5);
  expect(inputBox.x + inputBox.width).toBeGreaterThanOrEqual(
    chipBox.x + chipBox.width + 3 - 0.5,
  );
  expect(inputBox.y + inputBox.height).toBeGreaterThanOrEqual(
    chipBox.y + chipBox.height + 3 - 0.5,
  );
  // Invisible but never click-through, and the focus ring is the chip's 2 px, not the platform's.
  await expect(input).toHaveCSS("opacity", "0");
  await input.focus();
  await expect(input).toHaveCSS("outline-style", "none");
  await expect(chip).toHaveCSS("outline-width", "2px");
  expect(failures).toEqual([]);
});

test("inline card: the link row is 44 px drawn with a 48 px target", async ({
  page,
}) => {
  const tasks = [1, 2, 3].map((n) => ({
    ...overdueTask,
    id: uid(10 + n),
    title: `Uppgift ${n}`,
  }));
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("work", "en"),
    width: 390,
    height: 844,
    hostContext: inline,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, {
    card: {
      kind: "work_changes",
      items: tasks,
      total: 3,
      truncated: false,
      issued_at: "2026-10-26T08:00:00Z",
    },
    items: tasks,
  });
  const link = app.getByRole("button", { name: "Show all (3)", exact: true });
  await expect(link).toBeVisible();
  expect((await boxOf(link)).height).toBe(44);
  expect((await effectiveTargetSize(link))?.height).toBe(TARGET_PX);
  expect(failures).toEqual([]);
});

test("inline Journal card: a linked contact is a 32 px chip with a 48 px target", async ({
  page,
}) => {
  const entry = {
    id: uid(20),
    title: "Mötet med Anna",
    summary: "Kunden vill ha offerten före fredag.",
    contact_ids: [uid(21)],
    task_ids: [],
    links: [{ kind: "contact", id: uid(21), label: "Anna Andersson" }],
  };
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("journal", "en"),
    width: 390,
    height: 844,
    hostContext: inline,
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { entry });
  const chip = app.getByRole("button", { name: "Anna Andersson", exact: true });
  await expect(chip).toBeVisible();
  expect((await boxOf(chip)).height).toBe(32);
  expect((await effectiveTargetSize(chip))?.height).toBe(TARGET_PX);
  expect(failures).toEqual([]);
});

const annaId = uid(30);
const contactList = {
  contacts: [{ id: annaId, display_name: "Anna Andersson", archived: false }],
  next_cursor: null,
  q: "",
  include_archived: false,
};
const annaRecord = {
  id: annaId,
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: null,
  relationship: "Leverantör",
  role: "Säljare och kundansvarig",
  organization: "Flyttfirman Väst Norrbotten AB",
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};

test("Contact view: the profile line is one muted line cut with an ellipsis, and the list's chevron goes at large text only", async ({
  page,
}) => {
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 800,
    hostContext: fullscreen,
    replies: {
      get_contact_context: {
        structuredContent: {
          contact: annaRecord,
          projects: { items: [], next_cursor: null },
          tasks: { items: [], next_cursor: null },
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, contactList);
  const rowButton = app.getByRole("button", {
    name: "Anna Andersson",
    exact: true,
  });
  const chevron = app.locator(".sk-row-chevron").first();
  await expect(chevron).toBeVisible();
  await app.locator("html").evaluate((root) => {
    root.style.fontSize = "32px";
  });
  await expect(chevron).toBeHidden();
  await app.locator("html").evaluate((root) => {
    root.style.fontSize = "";
  });
  await expect(chevron).toBeVisible();
  await rowButton.click();
  const profile = app.locator(".work-contact-profile");
  await expect(profile).toBeVisible();
  const line = await profile.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      whiteSpace: style.whiteSpace,
      textOverflow: style.textOverflow,
      lineHeight: Number.parseFloat(style.lineHeight),
      height: element.getBoundingClientRect().height,
      cut: element.scrollWidth > element.clientWidth,
    };
  });
  expect(line.whiteSpace).toBe("nowrap");
  expect(line.textOverflow).toBe("ellipsis");
  expect(line.height).toBeLessThanOrEqual(line.lineHeight + 1);
  expect(line.cut).toBe(true);
  expect(failures).toEqual([]);
});

test("full view: every room tab and the Back row are 48 px targets, and the tabs follow each other without overlapping", async ({
  page,
}) => {
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", "sv"),
    width: 375,
    height: 780,
    hostContext: {
      ...fullscreen,
      toolInfo: { id: 1, tool: { name: "get_journal_entry" } },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: domainReplies(),
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, opening.journalEntry);
  const tabs = app.getByRole("navigation", { name: "Rum" }).getByRole("button");
  expect(await tabs.count()).toBe(4);
  let previousRight = -Infinity;
  for (const tab of await tabs.all()) {
    const box = await boxOf(tab);
    expect((await effectiveTargetSize(tab))?.height).toBeGreaterThanOrEqual(
      TARGET_PX,
    );
    // The boxes follow each other along the strip: a tab's target never reaches into the next one's.
    expect(box.x).toBeGreaterThanOrEqual(previousRight - 0.5);
    previousRight = box.x + box.width;
  }
  const back = app.getByRole("button", { name: /^Tillbaka/ });
  expect((await effectiveTargetSize(back))?.height).toBeGreaterThanOrEqual(
    TARGET_PX,
  );
  expect(failures).toEqual([]);
});

test("Agenda: a group heading stuck over its rows takes every tap on it, never the ring of a row scrolled under it (ui-1)", async ({
  page,
}) => {
  // Eight overdue Tasks, so the group outgrows the frame and a row can lie under its stuck heading.
  const items = Array.from({ length: 8 }, (_, i) => ({
    ...overdueTask,
    id: uid(100 + i),
    title: `Försenad uppgift ${i + 1} med en titel som bryts på två rader i en smal ram`,
    priority: "normal",
    project_title: null,
  }));
  const longAgenda = { items, next_cursor: null };
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("work"),
    width: 360,
    height: 520,
    hostContext: fullscreen,
    replies: { get_work_agenda: { structuredContent: longAgenda } },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, longAgenda);
  await expect(app.locator(".work-agenda-row")).toHaveCount(8);
  const probe = await app.locator("html").evaluate(async () => {
    const head = document.querySelector<HTMLElement>(
      ".work-agenda-group-head",
    )!;
    const rings = [
      ...document.querySelectorAll<HTMLElement>("button.work-agenda-glyph"),
    ];
    const stuckTop = parseFloat(getComputedStyle(head).top);
    const frame = () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      );
    const result = { checked: 0, ringUnder: 0, misses: [] as string[] };
    // Step the scroll so that ring after ring passes under the stuck heading.
    for (let scroll = 0; scroll < 600; scroll += 12) {
      document.scrollingElement!.scrollTop = scroll;
      await frame();
      const box = head.getBoundingClientRect();
      if (Math.abs(box.top - stuckTop) > 1) continue;
      const under = rings.some((ring) => {
        const r = ring.getBoundingClientRect();
        return r.bottom > box.top && r.top < box.bottom;
      });
      if (under) result.ringUnder++;
      for (let x = 2; x < box.right; x += 8)
        for (const y of [
          box.top + 2,
          box.top + box.height / 2,
          box.bottom - 2,
        ]) {
          result.checked++;
          const hit = document.elementFromPoint(x, y);
          if (!hit || !head.contains(hit))
            result.misses.push(
              `${scroll}:${Math.round(x)},${Math.round(y)} → ${hit?.tagName}.${String(hit?.className)}`,
            );
        }
    }
    return result;
  });
  expect(
    probe.ringUnder,
    "a ring passed under the stuck heading",
  ).toBeGreaterThan(0);
  expect(probe.checked).toBeGreaterThan(0);
  expect(probe.misses).toEqual([]);
  expect(failures).toEqual([]);
});
