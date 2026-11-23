import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { chooseView, goRoom, openSidekick } from "./app-navigation-fixtures";
import { box, style } from "./computed-style";
import { settled } from "./mcp-host-fixture";
import {
  bigAgenda,
  controlReplies,
  journalReplies,
  workReplies,
} from "./one-screen-fixtures";

// The shared room head (desktop spec 2.2) measured in a real Chromium: in a wide frame (>= 64rem) the room's tabs and
// tools stand in the shell's bar, after the room strip, in one row, and the tools keep the same places in every room
// and view. SIMULATED host only (mcp-host-fixture.ts: every tool answer is a fixture); this is not a run in a real
// Claude or Android host.

const replies = { ...workReplies, ...journalReplies, ...controlReplies };

async function open(page: Page, width: number, height: number) {
  await page.clock.setFixedTime(new Date("2026-11-03T12:00:00Z"));
  const opened = await openSidekick(page, {
    width,
    height,
    theme: "light",
    tool: "get_work_agenda",
    result: bigAgenda,
    replies,
    platform: "desktop",
  });
  await settled(opened.app);
  await expect(opened.app.locator(".sk-room-head")).toBeVisible();
  return opened;
}

/**
 * The middle of the head's tool cells, counted from the right: the last three drawn cells are search, + and ⋯, each an
 * empty box where a view has no such tool. A room may wrap its ⋯ (Work's `.work-agenda-more`), so the cells are found
 * by class, not as the row's children; a cell that is not drawn has no width.
 */
async function toolMiddles(app: FrameLocator) {
  return app
    .locator(".sk-room-head:visible")
    .first()
    .evaluate((row) => {
      const cells = Array.from(
        row.querySelectorAll(".sk-room-head__tool, .sk-room-head__slot"),
      ).filter((cell) => cell.getBoundingClientRect().width > 0);
      const middles = cells.slice(-3).map((cell) => {
        const rect = cell.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      });
      return { search: middles[0]!, add: middles[1]!, more: middles[2]! };
    });
}

const firstTab = (app: FrameLocator) =>
  app.locator(".sk-room-head__tabs button").first();

async function openControl(app: FrameLocator) {
  await app.locator(".sk-room-head__tool:visible").last().click();
  await app.getByRole("button", { name: "Minne och kontroll" }).click();
  await expect(
    app.getByRole("heading", { level: 2, name: "Minne och kontroll" }),
  ).toBeVisible();
  await settled(app);
}

test("Desktop head at 1440 x 900: one 56 row in the bar, and + has the same middle in Agenda, Status, Projekt, Dagbok Dag and Vecka and Kontroll", async ({
  page,
}) => {
  const { app, failures } = await open(page, 1440, 900);
  await expect(app.locator(".sk-rooms-shell")).toHaveAttribute(
    "data-head",
    "on",
  );
  // The head is in the bar's row, after the strip: one row, 56 at most.
  const bar = app.locator(".sk-rooms__bar");
  expect((await box(bar)).height).toBeLessThanOrEqual(56);
  await expect(
    app.locator(".sk-rooms__bar .sk-rooms__head .sk-room-head"),
  ).toHaveAttribute("data-place", "bar");

  const agenda = await toolMiddles(app);
  const agendaTab = await box(firstTab(app));
  // The tools are as measured in the simulated host: 1228, 1276 and 1324 from the left.
  expect(agenda.search.x).toBeCloseTo(1228, 0);
  expect(agenda.add.x).toBeCloseTo(1276, 0);
  expect(agenda.more.x).toBeCloseTo(1324, 0);

  const same = (
    name: string,
    got: { x: number; y: number },
    want: { x: number; y: number },
  ) => {
    expect(Math.abs(got.x - want.x), `${name}: x of the + cell`).toBeLessThan(
      0.5,
    );
    expect(Math.abs(got.y - want.y), `${name}: y of the + cell`).toBeLessThan(
      0.5,
    );
  };

  await chooseView(app, "Status", 1440);
  await settled(app);
  const status = await toolMiddles(app);
  same("Status", status.add, agenda.add);
  // The tabs do not move between the views of a room.
  expect(Math.abs((await box(firstTab(app))).x - agendaTab.x)).toBeLessThan(
    0.5,
  );

  await chooseView(app, "Projekt", 1440);
  await settled(app);
  same("Projekt", (await toolMiddles(app)).add, agenda.add);

  await goRoom(app, "Dagbok");
  await settled(app);
  // In a wide frame the day's strip gives way to the month rail (desktop spec 3.2).
  await expect(app.locator(".sk-month-rail")).toBeVisible();
  same("Dagbok Dag", (await toolMiddles(app)).add, agenda.add);

  // The day's + is the round ink + of the other rooms: a 32 circle in its 44 box.
  const add = app.locator(".sk-room-head__add:visible");
  const round = await style(
    add,
    "borderRadius",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "borderTopWidth",
    "borderLeftWidth",
    "boxSizing",
  );
  const addBox = await box(add);
  expect(round.borderRadius).toBe("50%");
  const px = (value: string) => Number.parseFloat(value);
  const inner = (side: "width" | "height") => {
    const [a, b] =
      side === "width"
        ? [round.paddingLeft, round.paddingRight]
        : [round.paddingTop, round.paddingBottom];
    return (
      addBox[side] -
      px(a!) -
      px(b!) -
      (round.borderTopWidth === "0px" && round.borderLeftWidth === "0px"
        ? 0
        : px(round.borderLeftWidth!) * 2)
    );
  };
  expect(inner("width")).toBeCloseTo(32, 0);
  expect(inner("height")).toBeCloseTo(32, 0);

  await app.getByRole("button", { name: "Vecka", exact: true }).click();
  await settled(app);
  await expect(app.locator(".sk-room-head:visible")).toHaveCount(1);
  same("Dagbok Vecka", (await toolMiddles(app)).add, agenda.add);

  await openControl(app);
  same("Kontroll", (await toolMiddles(app)).add, agenda.add);
  expect(failures).toEqual([]);
});

test("Desktop head at 1440 x 900: ? opens the keyboard help and Esc closes it", async ({
  page,
}) => {
  const { app, failures } = await open(page, 1440, 900);
  await app.getByRole("button", { name: "Arbete", exact: true }).focus();
  await page.keyboard.press("?");
  const dialog = app.getByRole("dialog", { name: "Kortkommandon" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Överallt" })).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: "Arbete", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(
    app.getByRole("button", { name: "Arbete", exact: true }),
  ).toBeFocused();
  expect(failures).toEqual([]);
});

test("Desktop head at 1440 x 900: g and a number goes to that room", async ({
  page,
}) => {
  const { app, failures } = await open(page, 1440, 900);
  await app.getByRole("button", { name: "Arbete", exact: true }).focus();
  await page.keyboard.press("g");
  await page.keyboard.press("2");
  await expect(
    app.getByRole("button", { name: "Dagbok", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  expect(failures).toEqual([]);
});

test("Phone head at 390 px: the head stands in the room, not in the bar, and the tools have the same middles in Agenda and Dag", async ({
  page,
}) => {
  const { app, failures } = await open(page, 390, 844);
  await expect(app.locator(".sk-rooms-shell")).not.toHaveAttribute(
    "data-head",
    "on",
  );
  await expect(app.locator(".sk-rooms__head")).toHaveCount(0);
  await expect(app.locator(".sk-room-head:visible")).toHaveAttribute(
    "data-place",
    "room",
  );
  const agenda = await toolMiddles(app);
  // As measured in the simulated host: search, + and ⋯ at 270, 318 and 366, 82 from the top (under the 48 strip).
  expect(agenda.search.x).toBeCloseTo(270, 0);
  expect(agenda.add.x).toBeCloseTo(318, 0);
  expect(agenda.more.x).toBeCloseTo(366, 0);
  expect(agenda.add.y).toBeCloseTo(82, 0);

  await goRoom(app, "Dagbok");
  await settled(app);
  await expect(app.locator(".sk-day-strip")).toBeVisible();
  const day = await toolMiddles(app);
  for (const tool of ["search", "add", "more"] as const) {
    expect(Math.abs(day[tool].x - agenda[tool].x), `${tool} x`).toBeLessThan(
      0.5,
    );
    expect(Math.abs(day[tool].y - agenda[tool].y), `${tool} y`).toBeLessThan(
      0.5,
    );
  }
  expect(failures).toEqual([]);
});
