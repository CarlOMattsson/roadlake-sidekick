import { expect, test, type Locator, type Page } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import {
  box,
  pseudoStyle,
  resolved,
  resolvedWithin,
  style,
} from "./computed-style";
import { effectiveTargetSize, settled } from "./mcp-host-fixture";
import { FIXTURE_NOW, iso, task, workReplies } from "./one-screen-fixtures";

// The Work agenda measured in a real Chromium from computed style and boxes, instead of read out of agenda.css:
// the meta line, the row's type and ring, the Undo line, the quick choices and the open row's surface. Simulated host
// (see mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture. Where a value comes
// from a design token, the expected value is the token resolved in the page.

const full = {
  ...task(0, "in_progress", {
    agenda_group: "overdue",
    due_at: iso(-2),
    priority: "high",
    project_title: "Renovering av köket",
  }),
  title: "Måla köket",
};
const plain = {
  ...task(1, "todo", {
    agenda_group: "today",
    due_at: iso(0, 14),
    priority: "normal",
    project_title: null,
  }),
  title: "Ring Anna",
};
const finished = {
  ...task(2, "completed", {
    agenda_group: "today",
    due_at: iso(0, 10),
    priority: "normal",
    project_title: null,
  }),
  title: "Skicka offert",
};
const projectRow = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Kök",
  status: "active",
  due_at: null,
  version: 1,
  agenda_group: "today",
};
const agenda = {
  items: [full, plain, finished, projectRow],
  next_cursor: null,
};

async function openAgenda(page: Page, width = 375) {
  await page.clock.setFixedTime(FIXTURE_NOW);
  const opened = await openSidekick(page, {
    width,
    theme: "light",
    tool: "get_work_agenda",
    result: agenda,
    replies: {
      ...workReplies,
      get_work_agenda: { structuredContent: agenda },
      update_task: {
        structuredContent: {
          task: { ...plain, status: "completed", version: 2 },
        },
      },
    },
  });
  await settled(opened.app);
  return opened;
}

const rowOf = (app: Locator, title: string) =>
  app.locator("li.work-agenda-row", { hasText: title });

/** The computed font of a type token, as a font shorthand set on a probe in the page. */
const typed = (scope: Locator, token: string) =>
  scope.evaluate((element, value) => {
    const probe = document.createElement("span");
    element.appendChild(probe);
    probe.style.font = value;
    const computed = getComputedStyle(probe);
    const out = {
      fontSize: computed.fontSize,
      fontWeight: computed.fontWeight,
      lineHeight: computed.lineHeight,
    };
    probe.remove();
    return out;
  }, `var(${token})`);

test("the meta line keeps its time and status whole, lets only the Project give way, and sits on the row's own air", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const row = rowOf(app.locator("body"), "Måla köket");
  const meta = row.locator(".work-card-meta");
  await expect(meta).toBeVisible();
  expect(
    await style(
      meta,
      "display",
      "flexWrap",
      "alignContent",
      "rowGap",
      "whiteSpace",
      "overflowX",
      "paddingTop",
      "paddingBottom",
    ),
  ).toEqual({
    display: "flex",
    flexWrap: "wrap",
    alignContent: "flex-start",
    rowGap: "0px",
    whiteSpace: "nowrap",
    overflowX: "clip",
    paddingTop: "0px",
    paddingBottom: "0px",
  });
  // The line is a floor of one meta line, not a fixed height; the gap is 0.8 em; the air under it is the row's pad.
  const [metaBox, line] = await Promise.all([
    box(meta),
    resolvedWithin(meta, "min-height", "var(--sk-type-meta-line)"),
  ]);
  expect(metaBox.height).toBeGreaterThanOrEqual(Number.parseFloat(line) - 0.5);
  expect(await style(meta, "minHeight", "columnGap", "marginBottom")).toEqual({
    minHeight: line,
    columnGap: await resolvedWithin(meta, "column-gap", "0.8em"),
    marginBottom: await resolved(app, "margin-bottom", "var(--sk-row-pad)"),
  });
  // Every part keeps its own width and ignores the pointer; only the Project shrinks, to 4em, with an ellipsis.
  const parts = await meta.locator("> *").all();
  expect(parts.length).toBeGreaterThanOrEqual(3);
  for (const part of parts) {
    const isProject = await part.evaluate((element) =>
      element.matches(".work-card-project"),
    );
    expect(
      await style(part, "position", "pointerEvents", "flexGrow", "flexShrink"),
    ).toEqual({
      position: "relative",
      pointerEvents: "none",
      flexGrow: isProject ? "1" : "0",
      flexShrink: isProject ? "1" : "0",
    });
  }
  const project = meta.locator(".work-card-project");
  expect(
    await style(
      project,
      "flexBasis",
      "maxWidth",
      "minWidth",
      "overflowX",
      "textOverflow",
    ),
  ).toEqual({
    flexBasis: await resolvedWithin(project, "flex-basis", "4em"),
    maxWidth: "max-content",
    minWidth: "0px",
    overflowX: "hidden",
    textOverflow: "ellipsis",
  });
  // Hög and the Project after another part wrap to a zero-high line the clip hides; the first part is not pulled up.
  expect(
    (await style(meta.locator(".work-card-priority"), "marginBottom"))
      .marginBottom,
  ).toBe(
    await resolvedWithin(
      meta,
      "margin-bottom",
      "calc(-1 * var(--sk-type-meta-line))",
    ),
  );
  expect((await style(parts[0]!, "marginBottom")).marginBottom).toBe("0px");
  // The separator hangs in the gap before its part, so a part that starts a line has no leading "·".
  expect(
    await pseudoStyle(parts[1]!, "::before", "content", "position"),
  ).toEqual({ content: '"·"', position: "absolute" });
  expect((await pseudoStyle(parts[0]!, "::before", "content")).content).toBe(
    "none",
  );
  // The kind is plain text: the board's pill frame is gone.
  const kind = rowOf(app.locator("body"), "Kök").locator(".work-card-kind");
  await expect(kind).toHaveCount(1);
  expect((await style(kind, "borderTopLeftRadius")).borderTopLeftRadius).toBe(
    "0px",
  );
  expect(failures).toEqual([]);
});

test("a row's title is the row type, its ring keeps 44 across, and a long word breaks only as a last resort", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const row = rowOf(app.locator("body"), "Måla köket");
  const title = row.locator(".work-agenda-body > button");
  await expect(title).toBeVisible();
  expect(await style(title, "overflowWrap", "hyphens")).toEqual({
    overflowWrap: "break-word",
    hyphens: "manual",
  });
  const rowType = await typed(title, "--sk-type-row");
  const metaType = await typed(title, "--sk-type-meta");
  expect(await style(title, "fontSize", "fontWeight", "lineHeight")).toEqual(
    rowType,
  );
  expect(
    await style(
      row.locator(".work-card-meta"),
      "fontSize",
      "fontWeight",
      "lineHeight",
    ),
  ).toEqual(metaType);
  // The title is 16 on a 1.3 line at least, the meta line 14 on a 1.25 line at least.
  const ratio = (type: Record<string, string>) =>
    Number.parseFloat(type.lineHeight!) / Number.parseFloat(type.fontSize!);
  expect(ratio(rowType)).toBeGreaterThanOrEqual(1.3 - 0.001);
  expect(ratio(metaType)).toBeGreaterThanOrEqual(1.25 - 0.001);
  // The ring's button is the leading column's width and hangs into the page margin; it is at least 44 across.
  const glyph = row.locator("button.work-agenda-glyph");
  const lead = await resolved(app, "width", "var(--sk-lead-w)");
  expect(
    await style(
      glyph,
      "width",
      "minWidth",
      "minHeight",
      "marginTop",
      "marginRight",
      "marginBottom",
    ),
  ).toEqual({
    width: lead,
    minWidth: lead,
    minHeight: await resolved(app, "height", "var(--sk-lead-h)"),
    marginTop: "0px",
    marginRight: "2px",
    marginBottom: "0px",
  });
  expect((await style(glyph, "marginLeft")).marginLeft).toBe(
    await resolved(app, "margin-left", "var(--sk-lead-hang)"),
  );
  expect((await box(glyph)).width).toBeGreaterThanOrEqual(44);
  // The ring is 24 to 32 px, and its target reaches 2 px past each side.
  const ring = await box(glyph.locator("svg"));
  expect(ring.width).toBeGreaterThanOrEqual(24);
  expect(ring.width).toBeLessThanOrEqual(32);
  expect(
    await pseudoStyle(glyph, "::after", "content", "position", "left", "right"),
  ).toEqual({
    content: '""',
    position: "absolute",
    left: "-2px",
    right: "-2px",
  });
  // The row has no padding of its own: the 6 of air over the title is a margin, and a row without a meta line holds
  // its 6 under the title as a margin too.
  const air = await resolved(app, "margin-top", "var(--sk-row-pad)");
  expect(await style(row, "paddingTop", "paddingBottom")).toEqual({
    paddingTop: "0px",
    paddingBottom: "0px",
  });
  expect(
    await style(title, "marginTop", "paddingTop", "paddingBottom"),
  ).toEqual({ marginTop: air, paddingTop: "0px", paddingBottom: "0px" });
  expect(failures).toEqual([]);
});

test("a finished Task's row is dimmed by its check glyph, a read shows Loading out of the flow", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const muted = await resolved(app, "color", "var(--sk-muted)");
  const body = (title: string) =>
    rowOf(app.locator("body"), title).locator(".work-agenda-body");
  await expect(body("Skicka offert")).toBeVisible();
  expect((await style(body("Skicka offert"), "color")).color).toBe(muted);
  expect((await style(body("Ring Anna"), "color")).color).not.toBe(muted);
  // Loading is a status line out of the flow: added to the list it takes no room and moves no row.
  const row = rowOf(app.locator("body"), "Ring Anna");
  const before = await box(row);
  await app.locator(".work-agenda").evaluate((list) => {
    const loading = document.createElement("p");
    loading.className = "work-agenda-loading";
    loading.setAttribute("role", "status");
    loading.textContent = "Laddar";
    list.prepend(loading);
  });
  expect(
    (await style(app.locator(".work-agenda-loading"), "position")).position,
  ).toBe("absolute");
  expect(await box(row)).toEqual(before);
  expect(failures).toEqual([]);
});

test("the Undo line has no surface of its own, holds no room below the list and never takes the pointer; Ångra is a compact button with a 48 target", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const row = rowOf(app.locator("body"), "Ring Anna");
  const list = app.locator(".work-agenda").first();
  const foot = (await style(list, "paddingBottom")).paddingBottom;
  await row.locator("button.work-agenda-glyph").click();
  const undo = row.getByRole("button", { name: /^Ångra/ });
  await expect(undo).toBeVisible();
  const wrapper = row.locator(".work-agenda-undo");
  const line = wrapper.locator("p");
  expect((await style(wrapper, "display")).display).toBe("contents");
  expect(
    await style(
      line,
      "color",
      "backgroundColor",
      "borderTopWidth",
      "boxShadow",
    ),
  ).toEqual({
    color: await resolved(app, "color", "var(--sk-muted)"),
    backgroundColor: "rgba(0, 0, 0, 0)",
    borderTopWidth: "0px",
    boxShadow: "none",
  });
  // Neither the line nor its row sticks, none of it is held off from the pointer, and the list reserves nothing.
  for (const part of [wrapper, line, row])
    expect((await style(part, "position")).position).not.toBe("sticky");
  expect((await style(line, "pointerEvents")).pointerEvents).not.toBe("none");
  expect((await style(list, "paddingBottom")).paddingBottom).toBe(foot);
  // Ångra stands in the trailing column on the title's row and the line under it, inside the row.
  const [rowBox, undoBox, titleBox] = await Promise.all([
    box(row),
    box(undo),
    box(row.locator(".work-agenda-body > button")),
  ]);
  expect(undoBox.x).toBeGreaterThan(titleBox.x);
  expect(undoBox.x + undoBox.width).toBeLessThanOrEqual(
    rowBox.x + rowBox.width + 0.5,
  );
  expect(undoBox.y).toBeGreaterThanOrEqual(rowBox.y - 0.5);
  // A compact secondary button: 40 drawn; its target reaches down into the row but never up into the one above; the time line runs along its foot for 15 s.
  expect((await style(undo, "minHeight")).minHeight).toBe(
    await resolved(app, "min-height", "var(--sk-compact)"),
  );
  expect((await effectiveTargetSize(undo))?.height).toBeGreaterThanOrEqual(44);
  expect((await pseudoStyle(undo, "::after", "top")).top).toBe("0px");
  expect(
    await pseudoStyle(
      undo,
      "::before",
      "animationName",
      "animationDuration",
      "animationTimingFunction",
      "animationFillMode",
      "animationPlayState",
    ),
  ).toEqual({
    animationName: "sk-undo-time",
    animationDuration: "15s",
    animationTimingFunction: "linear",
    animationFillMode: "forwards",
    animationPlayState: "running",
  });
  // The time line stands still while the pointer is over the line.
  await undo.hover();
  await expect
    .poll(
      async () =>
        (await pseudoStyle(undo, "::before", "animationPlayState"))
          .animationPlayState,
    )
    .toBe("paused");
  expect(failures).toEqual([]);
});

test("the Undo time line is not drawn with reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { app, failures } = await openAgenda(page);
  const row = rowOf(app.locator("body"), "Ring Anna");
  await row.locator("button.work-agenda-glyph").click();
  const undo = row.getByRole("button", { name: /^Ångra/ });
  await expect(undo).toBeVisible();
  expect(
    await pseudoStyle(undo, "::before", "content", "animationName"),
  ).toEqual({ content: "none", animationName: "none" });
  expect(failures).toEqual([]);
});

test("an opened row is one surface with the card radius and a border edge; its choices wrap, the date input lies invisibly over its chip", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const row = rowOf(app.locator("body"), "Ring Anna");
  await row.click({ button: "right" });
  const menu = row.locator(".work-agenda-menu");
  await expect(menu).toBeVisible();
  expect(
    await style(row, "backgroundColor", "borderTopLeftRadius", "boxShadow"),
  ).toEqual({
    backgroundColor: await resolved(
      app,
      "background-color",
      "var(--sk-surface)",
    ),
    borderTopLeftRadius: await resolved(
      app,
      "border-top-left-radius",
      "var(--sk-radius-card)",
    ),
    boxShadow: await resolved(
      app,
      "box-shadow",
      "inset 0 0 0 var(--sk-hairline) var(--sk-border)",
    ),
  });
  // The menu inside it has no background of its own, and its chips start on the title's x.
  expect((await style(menu, "backgroundColor")).backgroundColor).toBe(
    "rgba(0, 0, 0, 0)",
  );
  const air = await resolved(app, "padding-top", "var(--sk-s2)");
  expect(
    await style(menu, "paddingTop", "paddingRight", "paddingBottom"),
  ).toEqual({ paddingTop: air, paddingRight: air, paddingBottom: air });
  expect((await style(menu, "paddingLeft")).paddingLeft).toBe(
    await resolved(
      app,
      "padding-left",
      "calc(var(--sk-lead-w) + var(--sk-lead-hang) + 2px)",
    ),
  );
  const choices = menu.locator(".work-agenda-choices").first();
  expect(await style(choices, "display", "flexWrap")).toEqual({
    display: "flex",
    flexWrap: "wrap",
  });
  // No field is drawn: the date input lies invisible over the chip's 48 target, 4 past its 1 px edge.
  const input = menu.locator(".work-agenda-date-input");
  expect(await style(input, "position", "opacity", "top", "left")).toEqual({
    position: "absolute",
    opacity: "0",
    top: await resolved(app, "top", "calc(-4px - var(--sk-hairline))"),
    left: await resolved(app, "left", "calc(-4px - var(--sk-hairline))"),
  });
  // The choices do not overlap the ring or the title: they start at or after the title's x.
  const [first, title] = await Promise.all([
    box(choices.getByRole("button").first()),
    box(row.locator(".work-agenda-body > button")),
  ]);
  expect(first.x).toBeGreaterThanOrEqual(title.x - 1);
  expect(failures).toEqual([]);
});

test("the long-press tip under the list is drawn in the meta type, muted, until a row's menu has been opened once", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const tip = app.locator(".work-row-tip").first();
  await expect(tip).toBeVisible();
  expect(await style(tip, "color", "marginTop")).toEqual({
    color: await resolved(app, "color", "var(--sk-muted)"),
    marginTop: "22px",
  });
  const metaType = await typed(tip, "--sk-type-meta");
  expect(await style(tip, "fontSize", "lineHeight")).toEqual({
    fontSize: metaType.fontSize,
    lineHeight: metaType.lineHeight,
  });
  await rowOf(app.locator("body"), "Ring Anna").click({ button: "right" });
  await expect(app.locator(".work-agenda-menu")).toBeVisible();
  await expect(tip).toBeHidden();
  expect(failures).toEqual([]);
});

test("the To sort row above the agenda takes the whole row and has a press area of at least 44 high", async ({
  page,
}) => {
  const { app, failures } = await openAgenda(page);
  const open = app.locator("button.work-unsorted-open");
  await expect(open).toBeVisible();
  const [openBox, rowBox] = await Promise.all([
    box(open),
    box(app.locator(".work-unsorted-open-row")),
  ]);
  expect(openBox.width).toBeCloseTo(rowBox.width, 0);
  expect(openBox.height).toBeGreaterThanOrEqual(44);
  expect((await style(open, "minHeight")).minHeight).toBe(
    await resolved(app, "min-height", "var(--sk-tap)"),
  );
  expect(failures).toEqual([]);
});
