import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import { journalDay, ok } from "./sidekick-domain-fixtures";
import { box, resolved, style } from "./computed-style";

// How the Journal looks, measured in a real Chromium from the computed style and the boxes of the rendered
// views, instead of read out of journal.css. Simulated host (see mcp-host-fixture.ts), not a real Claude or Android
// host: every tool answer is a fixture. Where a value comes from a design token, the expected value is the token
// resolved in the page, so a retuned token does not break the test but a rule that stops using it does.

const fullscreen = {
  locale: "en",
  theme: "light",
  displayMode: "fullscreen",
  availableDisplayModes: ["inline", "fullscreen"],
};

const draftId = "019f0000-0000-7000-8000-0000000000d1";
const projectId = "019f0000-0000-7000-8000-0000000000p1";
const sourceId = "019f0000-0000-7000-8000-0000000000s1";
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

async function openDay(
  page: Page,
  width: number,
  day: object = journalDay,
  hostCapabilities?: Record<string, unknown>,
) {
  // Today is 21 Oct 2026, in the week of the shown day (24 Oct).
  await page.clock.setFixedTime(new Date("2026-10-21T12:00:00Z"));
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("journal", "en"),
    width,
    height: 900,
    hostContext: fullscreen,
    hostCapabilities,
    replies: {
      get_journal_day: ok(day),
      get_journal_entry: ok({ entry: journalDay.entries[0] }),
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, day);
  await settled(opened.app);
  return opened;
}

for (const [width, gap] of [
  [500, 4],
  [320, 2],
] as const) {
  test(`Journal day view at ${width} px: seven equal day cells ${gap} px apart, no frame on a day, a selected day drawn as the chosen room`, async ({
    page,
  }) => {
    const { app, failures } = await openDay(page, width);
    const days = app.locator(".sk-day-strip-day");
    await expect(days).toHaveCount(7);
    const boxes = await Promise.all((await days.all()).map(box));
    for (const cell of boxes) {
      expect(Math.abs(cell.width - boxes[0]!.width)).toBeLessThan(0.5);
      expect(cell.height).toBeGreaterThanOrEqual(56);
    }
    for (let i = 1; i < boxes.length; i += 1)
      expect(boxes[i]!.x - (boxes[i - 1]!.x + boxes[i - 1]!.width)).toBeCloseTo(
        gap,
        0,
      );
    const week = app.locator(".sk-day-strip-week");
    expect(await style(week, "overflowX", "scrollSnapType")).toEqual({
      overflowX: "auto",
      scrollSnapType: "none",
    });
    // No 44 px floor on a cell or its list item, so seven cells fit a 320 px screen.
    for (const cell of [
      days.first(),
      app.locator(".sk-day-strip-week > li").first(),
    ])
      expect((await style(cell, "minWidth")).minWidth).toBe("0px");
    expect(
      await style(days.first(), "borderTopWidth", "borderLeftWidth"),
    ).toEqual({ borderTopWidth: "0px", borderLeftWidth: "0px" });
    // The chosen day: the page colour, a 2 px inset outline in the text colour, the text colour; no border.
    const selected = app.locator('.sk-day-strip-day[aria-current="date"]');
    expect(
      await style(selected, "backgroundColor", "color", "boxShadow"),
    ).toEqual({
      backgroundColor: await resolved(
        app,
        "background-color",
        "var(--sk-nav-active-bg)",
      ),
      color: await resolved(app, "color", "var(--sk-nav-active-fg)"),
      boxShadow: await resolved(
        app,
        "box-shadow",
        "inset 0 0 0 var(--sk-selected-width) var(--sk-nav-active-line)",
      ),
    });
    const dot = await box(app.locator(".sk-day-strip-dot"));
    expect(dot.width).toBe(6);
    expect(dot.height).toBe(6);
    expect(
      (await style(app.locator(".sk-day-strip-dot"), "borderRadius"))
        .borderRadius,
    ).toBe("50%");
    expect(failures).toEqual([]);
  });
}

test("Journal day view: the title row holds the title and the + at its end, the week row sits under it at the start in 48 px icon buttons", async ({
  page,
}) => {
  const { app, failures } = await openDay(page, 360);
  const head = app.locator(".sk-day-strip-head");
  const title = await box(app.locator(".sk-day-strip-title"));
  const add = app.locator(".journal-day-add");
  const weekrow = await box(app.locator(".sk-day-strip-weekrow"));
  expect(await style(head, "display")).toEqual({ display: "grid" });
  const gapUnder = await resolved(app, "margin-top", "var(--sk-s3)");
  expect((await style(head, "marginTop")).marginTop).toBe(gapUnder);
  // Title and + share a row, the + at the end; the week row is under both and starts at the title's edge.
  const addBox = await box(add);
  expect(
    Math.abs(addBox.y + addBox.height / 2 - (title.y + title.height / 2)),
  ).toBeLessThan(addBox.height);
  expect(addBox.x).toBeGreaterThan(title.x + title.width - 1);
  expect(weekrow.y).toBeGreaterThanOrEqual(title.y + title.height - 1);
  // The + and the week arrows are 48 x 48 boxes with a 24 px glyph at every text size.
  for (const button of [
    add,
    ...(await app.locator(".sk-day-strip-arrow").all()),
  ]) {
    const size = await box(button);
    expect([size.width, size.height]).toEqual([48, 48]);
    const glyph = await box(button.locator("svg"));
    expect([glyph.width, glyph.height]).toEqual([24, 24]);
  }
  // The first arrow's glyph, not its box, starts at the title's edge.
  const firstGlyph = await box(app.locator(".sk-day-strip-arrow svg").first());
  expect(firstGlyph.x).toBeCloseTo(title.x, 0);
  // The range is one line of meta type between the arrows.
  const range = app.locator(".journal-day-range");
  expect((await style(range, "whiteSpace")).whiteSpace).toBe("nowrap");
  const [arrowA, arrowB] = await Promise.all(
    (await app.locator(".sk-day-strip-arrow").all()).map(box),
  );
  const rangeBox = await box(range);
  expect(rangeBox.x).toBeGreaterThanOrEqual(arrowA!.x + arrowA!.width - 1);
  expect(rangeBox.x + rangeBox.width).toBeLessThanOrEqual(arrowB!.x + 1);
  // The spent next-week arrow reads in the border colour at full opacity, not as faded ink.
  expect(
    await style(
      app.locator('.sk-day-strip-arrow[aria-disabled="true"]'),
      "color",
      "opacity",
    ),
  ).toEqual({
    color: await resolved(app, "color", "var(--sk-border)"),
    opacity: "1",
  });
  expect(failures).toEqual([]);
});

test("Journal day view: h2 and h3 take the type of their level, the section heading in the text colour, with air under the summary", async ({
  page,
}) => {
  const { app, failures } = await openDay(page, 360);
  const h2 = app.locator("h2").first();
  const h3 = app.getByRole("heading", { level: 3 }).first();
  const fontOf = (locator: Locator) =>
    style(locator, "fontSize", "fontWeight", "lineHeight");
  const typed = async (token: string) =>
    app.locator("#root").evaluate((root, value) => {
      const probe = document.createElement("span");
      root.appendChild(probe);
      probe.style.font = value;
      const out = {
        fontSize: getComputedStyle(probe).fontSize,
        fontWeight: getComputedStyle(probe).fontWeight,
        lineHeight: getComputedStyle(probe).lineHeight,
      };
      probe.remove();
      return out;
    }, `var(${token})`);
  expect(await fontOf(h2)).toEqual(await typed("--sk-type-title"));
  expect(await fontOf(h3)).toEqual(await typed("--sk-type-section"));
  expect((await style(h3, "color")).color).toBe(
    await resolved(app, "color", "var(--sk-fg)"),
  );
  // The summary is body size on the row title's line height; the first heading after it stands 16 below.
  const summary = app.locator(".journal-day-summary > p").last();
  expect((await style(summary, "lineHeight")).lineHeight).toBe(
    (await typed("--sk-type-row")).lineHeight,
  );
  expect((await style(h3, "marginTop")).marginTop).toBe(
    await resolved(app, "margin-top", "var(--sk-s4)"),
  );
  expect(failures).toEqual([]);
});

test("Journal day view: an empty day stands 12 px under the strip, and the + opens two 48 px choices", async ({
  page,
}) => {
  const empty = {
    ...journalDay,
    entries: [],
    summary: { ...journalDay.summary, exists: false, content: null },
  };
  const { app, failures } = await openDay(page, 360, empty, { message: {} });
  const gap = await resolved(app, "padding-top", "var(--sk-s3)");
  // The empty day's own state stands 12 under the strip, and its write button is a 48 px target.
  const state = app.locator(".journal-empty-state > .sk-empty");
  await expect(state).toBeVisible();
  expect((await style(state, "paddingTop")).paddingTop).toBe(gap);
  expect(
    (await box(app.locator(".journal-write-self"))).height,
  ).toBeGreaterThanOrEqual(48);
  // Opened for writing, the day says only its sentence, 12 under the strip, over two 48 px choices.
  await app.getByRole("button", { name: "New entry" }).click();
  expect(
    (await style(app.locator(".journal-empty"), "marginTop")).marginTop,
  ).toBe(await resolved(app, "margin-top", "var(--sk-s3)"));
  const choices = app.locator(".journal-add-panel > .journal-add-choice");
  await expect(choices).toHaveCount(2);
  for (const choice of await choices.all())
    expect((await box(choice)).height).toBeGreaterThanOrEqual(48);
  expect(failures).toEqual([]);
});

test("Journal draft review: an unpressed option is ink on a border ring, the chosen Godkänn and Avslå take their status tone, the bar sticks only above 400 px", async ({
  page,
}) => {
  const { app, failures } = await (async () => {
    const opened = await openSimulatedApp(page, {
      resource: readBuiltApp("journal", "en"),
      width: 500,
      height: 900,
      hostContext: fullscreen,
      replies: {
        list_pending_journal: ok(pending),
        get_journal_draft: ok({ draft, source }),
      },
    });
    await waitForAppInitialized(page);
    await deliverToolResult(page, pending);
    await settled(opened.app);
    return opened;
  })();
  await app.getByRole("button", { name: /^Utkast om offerten/ }).click();
  const flat = app.locator(".journal-check-flat").first();
  await expect(flat).toBeVisible();
  const options = flat.getByRole("button");
  const [first, second] = [options.nth(0), options.nth(1)];
  const ink = {
    color: await resolved(app, "color", "var(--sk-fg)"),
    boxShadow: await resolved(
      app,
      "box-shadow",
      "inset 0 0 0 1px var(--sk-border)",
    ),
  };
  await expect(first).toHaveAttribute("aria-pressed", "false");
  expect(await style(first, "color", "boxShadow")).toEqual(ink);
  for (const [option, tone] of [
    [first, "success"],
    [second, "danger"],
  ] as const) {
    await option.click();
    await expect(option).toHaveAttribute("aria-pressed", "true");
    expect(
      await style(option, "backgroundColor", "color", "boxShadow"),
    ).toEqual({
      backgroundColor: await resolved(
        app,
        "background-color",
        `var(--sk-${tone}-bg)`,
      ),
      color: await resolved(app, "color", `var(--sk-${tone}-fg)`),
      boxShadow: await resolved(
        app,
        "box-shadow",
        `inset 0 0 0 1px var(--sk-${tone}-line)`,
      ),
    });
  }
  // Above 400 px the decision bar sticks to the bottom on the card surface.
  const bar = app.locator(".journal-decision-bar");
  const stuck = await style(bar, "position", "bottom", "backgroundColor");
  expect(Number.parseFloat(stuck.bottom ?? "")).toBeGreaterThanOrEqual(0);
  expect({
    position: stuck.position,
    backgroundColor: stuck.backgroundColor,
  }).toEqual({
    position: "sticky",
    backgroundColor: await resolved(
      app,
      "background-color",
      "var(--sk-surface)",
    ),
  });
  // The quiet toggle that leads a line has no side padding, so it aligns with the heading, and keeps a 44 px width.
  const toggle = app.getByRole("button", { name: "Show original" });
  expect(await style(toggle, "paddingLeft", "paddingRight")).toEqual({
    paddingLeft: "0px",
    paddingRight: "0px",
  });
  expect((await box(toggle)).width).toBeGreaterThanOrEqual(44);
  // The destructive level is red text with no fill and no edge.
  await app.getByRole("button", { name: "Reject draft" }).click();
  expect(
    await style(
      app.getByRole("button", { name: "Yes, reject draft" }),
      "color",
      "backgroundColor",
      "borderTopColor",
      "boxShadow",
    ),
  ).toEqual({
    color: await resolved(app, "color", "var(--sk-overdue-fg)"),
    backgroundColor: "rgba(0, 0, 0, 0)",
    borderTopColor: "rgba(0, 0, 0, 0)",
    boxShadow: "none",
  });
  expect(failures).toEqual([]);
});

test("Journal entry view: Back leads the line without side padding, and the tag button is framed in the family's edge colour", async ({
  page,
}) => {
  const { app, failures } = await openDay(page, 360, journalDay, {
    message: {},
  });
  await app.getByRole("button", { name: /^Lunch med Anna/ }).click();
  const back = app.getByRole("button", { name: "Back", exact: true });
  await expect(back).toBeVisible();
  expect(await style(back, "paddingLeft", "paddingRight")).toEqual({
    paddingLeft: "0px",
    paddingRight: "0px",
  });
  // The quiet level: no fill and no edge, in the text colour.
  expect(
    await style(back, "backgroundColor", "borderTopColor", "color"),
  ).toEqual({
    backgroundColor: "rgba(0, 0, 0, 0)",
    borderTopColor: "rgba(0, 0, 0, 0)",
    color: await resolved(app, "color", "var(--sk-fg)"),
  });
  const tag = app.locator(".journal-entry-view .sk-tag-field__open");
  await expect(tag).toBeVisible();
  expect((await style(tag, "borderTopColor")).borderTopColor).toBe(
    await resolved(app, "color", "var(--sk-border)"),
  );
  expect(failures).toEqual([]);
});

test("Journal pending list: Show all reads as a link at body weight, not as a heading", async ({
  page,
}) => {
  const items = Array.from({ length: 5 }, (_, n) => ({
    ...pending.items[0]!,
    source_id: `019f0000-0000-7000-8000-${String(n + 40).padStart(12, "0")}`,
    draft_id: null,
    state: "extracting",
  }));
  const { app, failures } = await openSimulatedApp(page, {
    resource: readBuiltApp("journal", "en"),
    width: 390,
    height: 900,
    hostContext: { ...fullscreen, displayMode: "inline" },
    replies: {},
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, { items });
  await settled(app);
  const more = app.locator(".journal-list-more > .sk-more");
  await expect(more).toBeVisible();
  expect((await style(more, "fontWeight")).fontWeight).toBe(
    await resolved(app, "font-weight", "var(--sk-weight-normal)"),
  );
  expect(failures).toEqual([]);
});

test("Journal day view: the ⋯ menu is a surface card with 44 px rows, after the + on the title row", async ({
  page,
}) => {
  const { app, failures } = await openDay(page, 360, journalDay, {
    serverTools: {},
    message: {},
  });
  const more = app.locator(".journal-day-more");
  await expect(more).toBeVisible();
  const [addBox, moreBox] = await Promise.all([
    box(app.locator(".journal-day-add")),
    box(more),
  ]);
  expect(moreBox.x).toBeGreaterThan(addBox.x + addBox.width - 1);
  await more.click();
  const panel = app.locator(".sk-menu-panel");
  await expect(panel).toBeVisible();
  expect((await style(panel, "backgroundColor")).backgroundColor).toBe(
    await resolved(app, "background-color", "var(--sk-surface)"),
  );
  const items = await app.locator(".sk-menu-item").all();
  expect(items.length).toBeGreaterThan(0);
  for (const item of items)
    expect((await box(item)).height).toBeGreaterThanOrEqual(44);
  expect(failures).toEqual([]);
});

for (const [width, side] of [
  [500, 24],
  [320, 16],
] as const) {
  test(`Journal day view at ${width} px: the row's › is the shared chevron, ${side} px wide and high`, async ({
    page,
  }) => {
    const { app, failures } = await openDay(page, width);
    const chevron = app.locator(".journal-entry-chevron svg").first();
    await expect(chevron).toBeVisible();
    const size = await box(chevron);
    expect([size.width, size.height]).toEqual([side, side]);
    expect(failures).toEqual([]);
  });
}
