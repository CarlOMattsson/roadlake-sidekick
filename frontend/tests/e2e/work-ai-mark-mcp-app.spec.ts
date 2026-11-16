import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { domainReplies, ok, task, workItem } from "./sidekick-domain-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  waitForAppInitialized,
} from "./mcp-host-fixture";

// The AI mark on the rows of the Agenda and Status, full and inline, in a real Chromium on the simulated host
// (mcp-host-fixture.ts), not a real Claude or Android host. The mark is a pill on the meta line: a marked row is as
// tall as an unmarked one, the pill stands whole inside the row, and it is read aloud in the app's language.

const id = (n: number) => `019f0000-0000-7000-8000-00000000080${n}`;
const possible = {
  ...workItem({ ...task, id: id(1), title: "Sammanfatta offerten" }),
  ai_possible: true,
};
const approved = {
  ...workItem({
    ...task,
    id: id(2),
    title: "Researcha leverantörer",
    status: "in_progress",
  }),
  ai_possible: true,
  ai_plan_approved: true,
};
const plain = workItem({ ...task, id: id(3), title: "Ring Anna" });
const agenda = {
  items: [possible, approved, plain],
  filters: {},
  next_cursor: null,
};
const board = {
  columns: {
    todo: [possible, plain],
    in_progress: [approved],
    blocked: [],
    completed: [],
  },
  next_cursor: null,
};

async function open(
  page: Page,
  view: "agenda" | "board",
  displayMode: "fullscreen" | "inline",
  width: number,
  theme: "light" | "dark",
) {
  await page.emulateMedia({ colorScheme: theme });
  const { app } = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", "sv"),
    width,
    height: 780,
    hostContext: {
      locale: "sv",
      theme,
      displayMode,
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: {
        id: 1,
        tool: {
          name: view === "agenda" ? "get_work_agenda" : "get_work_board",
        },
      },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: {
      ...domainReplies(),
      get_work_agenda: ok(agenda),
      get_work_board: ok(board),
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, view === "agenda" ? agenda : board);
  return app;
}

/** The mark of the row titled `title`, and how its box lies in the row's meta line and in the viewport. */
async function measure(app: FrameLocator, title: string, name: string) {
  const mark = app
    .locator("li", { hasText: title })
    .getByRole("img", { name, exact: true });
  await expect(mark).toBeVisible();
  return mark.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const meta = el.parentElement!.getBoundingClientRect();
    return {
      inMeta:
        box.top >= meta.top - 0.5 &&
        box.bottom <= meta.bottom + 0.5 &&
        box.left >= meta.left - 0.5,
      inView: box.right <= document.documentElement.clientWidth,
      metaHeight: meta.height,
    };
  });
}

async function metaHeight(app: FrameLocator, title: string) {
  return app
    .locator("li", { hasText: title })
    .locator(".work-card-meta, .work-compact-row-meta")
    .evaluate((el) => el.getBoundingClientRect().height);
}

for (const width of [320, 412])
  for (const theme of ["light", "dark"] as const)
    for (const [view, mode] of [
      ["agenda", "fullscreen"],
      ["board", "fullscreen"],
      ["agenda", "inline"],
      ["board", "inline"],
    ] as const)
      test(`${view} ${mode}: the AI mark stands whole on the meta line (${width} px, ${theme})`, async ({
        page,
      }) => {
        // A board result opens on Status, an agenda result on the Agenda.
        const app = await open(page, view, mode, width, theme);
        const one = await measure(app, possible.title, "Möjlig med AI");
        const two = await measure(app, approved.title, "AI-plan godkänd");
        const line = await metaHeight(app, plain.title);
        for (const mark of [one, two]) {
          expect(mark.inMeta).toBe(true);
          expect(mark.inView).toBe(true);
          // No extra line: the marked row's meta is as tall as the unmarked row's.
          expect(Math.abs(mark.metaHeight - line)).toBeLessThan(1);
        }
      });
