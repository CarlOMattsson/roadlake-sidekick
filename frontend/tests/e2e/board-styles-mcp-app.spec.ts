import { expect, test, type Page } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import {
  box,
  pseudoStyle,
  resolved,
  resolvedWithin,
  style,
} from "./computed-style";
import { settled } from "./mcp-host-fixture";
import { FIXTURE_NOW, iso, task, workReplies } from "./one-screen-fixtures";

// The Work board (Status) measured in a real Chromium from computed style and boxes, instead of read out of work.css:
// the columns layout of a wide frame and the single list of a phone. Simulated host (see mcp-host-fixture.ts), not a
// real Claude or Android host: every tool answer is a fixture. Where a value comes from a design token, the expected
// value is the token resolved in the page.

const withMeta = {
  ...task(0, "todo", {
    due_at: iso(1),
    priority: "high",
    project_title: "Bokslut och skatt",
  }),
  title: "Skicka deklarationen",
};
const bare = {
  ...task(1, "todo", {
    due_at: null,
    priority: "normal",
    project_title: null,
    tags: [],
  }),
  title: "Ring Anna",
};
const doing = {
  ...task(2, "in_progress", {
    due_at: iso(0, 14),
    priority: "normal",
    project_title: null,
  }),
  title: "Måla köket",
};
const finished = {
  ...task(3, "completed", {
    due_at: null,
    priority: "normal",
    project_title: null,
  }),
  title: "Betala fakturan",
};
const projectCard = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Renovering av köket",
  status: "active",
  due_at: null,
  version: 1,
  project_title: null,
};
const board = {
  columns: {
    todo: [withMeta, bare],
    in_progress: [doing],
    blocked: [],
    completed: [finished],
    project: [projectCard],
  },
  next_cursor: null,
};

async function openBoard(page: Page, width: number) {
  await page.clock.setFixedTime(FIXTURE_NOW);
  const opened = await openSidekick(page, {
    width,
    theme: "light",
    tool: "get_work_board",
    result: board,
    replies: { ...workReplies, get_work_board: { structuredContent: board } },
  });
  await settled(opened.app);
  return opened;
}

test("Status on a wide frame: four columns share the row from 13.25rem, Projects are a row of their own, no column scrolls by itself", async ({
  page,
}) => {
  const { app, failures } = await openBoard(page, 1000);
  const columns = app.locator(".sk-shell .work-columns");
  await expect(columns).toBeVisible();
  const minimum = await resolvedWithin(columns, "width", "13.25rem");
  expect(
    await style(columns, "display", "overflowX", "--work-column-min"),
  ).toEqual({
    display: "grid",
    overflowX: "auto",
    "--work-column-min": "13.25rem",
  });
  const tracks = (await style(columns, "gridTemplateColumns"))
    .gridTemplateColumns!.split(" ")
    .map(Number.parseFloat);
  expect(tracks).toHaveLength(4);
  for (const track of tracks)
    expect(track).toBeGreaterThanOrEqual(Number.parseFloat(minimum) - 0.5);
  // The Projects column is the whole row, under the statuses.
  const project = columns.locator(
    '> .work-column[data-board-column="project"]',
  );
  await expect(project).toBeVisible();
  const [row, projectBox, firstStatus] = await Promise.all([
    box(columns),
    box(project),
    box(columns.locator('> .work-column[data-board-column="todo"]')),
  ]);
  expect(projectBox.width).toBeGreaterThan(row.width - 2);
  expect(projectBox.y).toBeGreaterThanOrEqual(
    firstStatus.y + firstStatus.height - 1,
  );
  // The page grows with the cards: a column has no height cap and no vertical scroll of its own.
  for (const column of await columns.locator("> .work-column").all())
    expect(await style(column, "maxHeight", "overflowY")).toEqual({
      maxHeight: "none",
      overflowY: "visible",
    });
  // A card's meta line keeps one nowrap row that wraps its parts; the Project is the part that is cut with an
  // ellipsis, and the time before it is cut too rather than clipped hard.
  const meta = columns.locator(".work-card-meta").first();
  expect(await style(meta, "whiteSpace", "flexWrap", "columnGap")).toEqual({
    whiteSpace: "nowrap",
    flexWrap: "wrap",
    columnGap: "0px",
  });
  const cut = columns.locator(".work-card-project").first();
  expect(await style(cut, "flexBasis", "overflowX", "textOverflow")).toEqual({
    flexBasis: await resolvedWithin(cut, "flex-basis", "6rem"),
    overflowX: "hidden",
    textOverflow: "ellipsis",
  });
  const due = meta.locator("span:not(.work-card-project)").first();
  expect(await style(due, "minWidth", "textOverflow")).toEqual({
    minWidth: "0px",
    textOverflow: "ellipsis",
  });
  // The dot is drawn before each part after the first, in a box of 0.8em of its own (the line has no gap), and is not
  // written in the text.
  const second = meta.locator("> *").nth(1);
  const dot = await pseudoStyle(
    second,
    "::before",
    "content",
    "display",
    "width",
    "fontSize",
  );
  expect(dot).toMatchObject({ content: '"·"', display: "inline-block" });
  expect(Number.parseFloat(dot.width!)).toBeCloseTo(
    0.8 * Number.parseFloat(dot.fontSize!),
    1,
  );
  expect(await second.evaluate((part) => part.textContent)).not.toContain("·");
  expect((await box(meta.locator("> *").first())).x).toBeLessThan(
    (await box(second)).x,
  );
  // Every hyphen is manual: Chromium's Swedish patterns split compounds wrongly.
  expect(
    (await style(app.locator(".sidekick-work").first(), "hyphens")).hyphens,
  ).toBe("manual");
  expect(failures).toEqual([]);
});

test("Status on a phone: one column at a time under 44 px column tabs, the section heading kept for screen readers, a card is a 48 row with no padding of its own, and the dot stands before Hög", async ({
  page,
}) => {
  const { app, failures } = await openBoard(page, 375);
  const single = app.locator('.work-board[data-layout="single"]');
  await expect(single).toBeVisible();
  // The phone shows one status at a time (user test 2026-11-20): column tabs, each a 44 px target with its count,
  // Pågår chosen first while something is in progress. The chosen section keeps its heading for screen readers
  // (visually hidden: the tab names it), and Klar under its tab opens at once, with no fold.
  const tabs = single.getByRole("group", { name: "Visa kolumn" });
  await expect(tabs).toBeVisible();
  const tab = (name: string) =>
    tabs.getByRole("button", { name: new RegExp(`^${name}\\s+\\d+$`) });
  for (const name of ["Att göra", "Pågår", "Blockerad", "Klar"])
    expect((await box(tab(name))).height).toBeGreaterThanOrEqual(44);
  await expect(tab("Pågår")).toHaveAttribute("aria-pressed", "true");
  await expect(tab("Att göra")).toHaveAccessibleName(/^Att göra\s+2$/);
  const heading = single.locator(".work-column > h3").first();
  await expect(heading).toHaveClass(/work-visually-hidden/);
  await expect(heading).toHaveText("Pågår (1)");
  await tab("Klar").click();
  await expect(single.locator("button.sk-fold")).toHaveCount(0);
  await expect(
    single.getByRole("button", { name: "Betala fakturan", exact: true }),
  ).toBeVisible();
  await tab("Att göra").click();
  // A card has no padding of its own and a floor of the row template's 48.
  const card = single.locator("li.work-card").first();
  expect(await style(card, "paddingTop", "paddingBottom", "minHeight")).toEqual(
    {
      paddingTop: "0px",
      paddingBottom: "0px",
      minHeight: await resolved(app, "min-height", "var(--sk-row-min)"),
    },
  );
  expect((await box(card)).height).toBeGreaterThanOrEqual(48);
  // A card without a meta line holds its 6 under the title as a margin, not a padding.
  const bareCard = single.locator("li.work-card", { hasText: "Ring Anna" });
  expect(
    (
      await style(
        bareCard
          .locator(".work-card-head > button:not(.work-card-done)")
          .first(),
        "marginBottom",
      )
    ).marginBottom,
  ).toBe(await resolved(app, "margin-bottom", "var(--sk-row-pad)"));
  // The dot before Hög hangs outside its box, so the part is not clipped.
  const priority = single.locator(".work-card-priority").first();
  expect((await style(priority, "overflowX")).overflowX).toBe("visible");
  expect(
    await pseudoStyle(priority, "::before", "content", "position"),
  ).toEqual({
    content: '"·"',
    position: "absolute",
  });
  expect(failures).toEqual([]);
});
