// Playwright runs this file outside Vitest: it reads the bundled app HTML (and font files) from disk to serve them to the simulated host.
import { readFileSync } from "node:fs";
import { test, expect, type FrameLocator } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
  type AppLocale,
} from "./mcp-host-fixture";

// The row's meta line in the Agenda and Status (agenda.css): the time,
// the status, the kind and the "High" marker always stand whole, whatever the width and text size; only the Project
// gives way (an ellipsis on it, or it leaves the line whole). The bug this guards: a one-line box with flex-wrap and
// overflow: clip dropped "Pågår" and the Project at 360 px and 200 % text. Simulated host in headless Chromium, not a
// real Claude or Android host. The app is drawn in Roboto Variable, embedded as in the UX harness (tests/ux), as
// Android phones draw it; the test machine's own Noto Sans is wider.

const ROBOTO_FAMILY = "Roboto Variable";
const ROBOTO_STACK = `'${ROBOTO_FAMILY}', Roboto, system-ui, sans-serif`;
let robotoCss: string | undefined;
function withRoboto(html: string): string {
  robotoCss ??= ["latin", "latin-ext"]
    .map((subset) => {
      const data = readFileSync(
        `node_modules/@fontsource-variable/roboto/files/roboto-${subset}-wght-normal.woff2`,
      ).toString("base64");
      return `@font-face{font-family:'${ROBOTO_FAMILY}';font-style:normal;font-display:block;font-weight:100 900;src:url(data:font/woff2;base64,${data}) format('woff2')}`;
    })
    .join("");
  return html.replace("<head>", `<head><style>${robotoCss}</style>`);
}

const NOW = "2026-11-04T10:00:00Z";
const uid = (n: number) =>
  `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`;
const row = (
  n: number,
  title: string,
  status: string,
  dueAt: string | null,
  group: string,
  extra: Record<string, unknown> = {},
) => ({
  kind: "task",
  id: uid(n),
  title,
  status,
  due_at: dueAt,
  priority: "normal",
  project_id: null,
  project_title: null,
  domain_accent: "blue",
  version: 1,
  agenda_group: group,
  ...extra,
});
const electrician = row(
  1,
  "Ring elektrikern om jordfelsbrytaren",
  "in_progress",
  "2026-10-24T09:00:00Z",
  "overdue",
  { project_id: uid(90), project_title: "Renovering av köket" },
);
const painter = row(
  2,
  "Boka målaren",
  "blocked",
  "2026-10-24T09:00:00Z",
  "overdue",
  { priority: "high" },
);
const invoice = row(
  3,
  "Skicka faktura",
  "in_progress",
  "2026-11-04T15:00:00Z",
  "today",
  { project_id: uid(91), project_title: "Bokslut 2026 och årsredovisning" },
);
const agenda = {
  items: [electrician, painter, invoice],
  filters: {},
  next_cursor: null,
};
const board = {
  columns: {
    todo: [painter],
    in_progress: [electrician, invoice],
    blocked: [],
    completed: [],
  },
  manually_ordered: [] as string[],
  next_cursor: null,
};

type Part = {
  cls: string;
  text: string;
  /** whole: inside the meta's box; omitted: wholly outside it; partial: neither. */
  fit: "whole" | "omitted" | "partial";
  ellipsis: boolean;
  /** Visible width of a partial part, in its own font size (em). */
  visibleEm: number;
  top: number;
};
type Meta = {
  title: string;
  parts: Part[];
  lines: number;
  /** The meta's width and what the parts that must stand need on one line (their boxes and the gaps between). */
  width: number;
  needs: number;
  /** The meta's height in its own lines (a hidden Hög or Project adds nothing). */
  heightInLines: number;
};

async function readMetas(app: FrameLocator, selector: string): Promise<Meta[]> {
  return app.locator("html").evaluate((doc, sel) => {
    const metas = [...doc.querySelectorAll<HTMLElement>(sel)];
    return metas.map((meta) => {
      const box = meta.getBoundingClientRect();
      const parts = [...meta.children].map((el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const inside =
          r.left >= box.left - 0.5 &&
          r.right <= box.right + 0.5 &&
          r.top >= box.top - 0.5 &&
          r.bottom <= box.bottom + 0.5;
        const outside =
          r.width === 0 ||
          r.top >= box.bottom - 0.5 ||
          r.bottom <= box.top + 0.5 ||
          r.left >= box.right - 0.5;
        const visible =
          Math.min(r.right, box.right) - Math.max(r.left, box.left);
        return {
          cls: el.className,
          text: el.textContent ?? "",
          fit: inside ? "whole" : outside ? "omitted" : "partial",
          ellipsis:
            cs.textOverflow === "ellipsis" &&
            (el as HTMLElement).scrollWidth > (el as HTMLElement).clientWidth,
          visibleEm: visible / Number.parseFloat(cs.fontSize),
          top: Math.round(r.top),
        } as const;
      });
      const shown = parts.filter((p) => p.fit !== "omitted");
      const must = [...meta.children].filter(
        (el) =>
          !el.classList.contains("work-card-project") &&
          !el.classList.contains("work-card-priority"),
      );
      const gap = Number.parseFloat(getComputedStyle(meta).columnGap) || 0;
      const needs = must.reduce(
        (sum, el, i) => sum + el.getBoundingClientRect().width + (i ? gap : 0),
        0,
      );
      const tops = [...new Set(shown.map((p) => p.top))];
      return {
        title: (meta.previousElementSibling?.textContent ?? "").slice(0, 24),
        parts,
        lines: tops.length,
        width: box.width,
        needs,
        heightInLines:
          box.height / Number.parseFloat(getComputedStyle(meta).lineHeight),
      };
    });
  }, selector);
}

const VIEWS = [
  {
    view: "Agenda",
    tool: "get_work_agenda",
    result: agenda,
    selector: ".work-agenda-body > .work-card-meta",
  },
  {
    view: "Status",
    tool: "get_work_board",
    result: board,
    selector:
      '.work-board[data-layout="single"] .work-list > li.work-card > .work-card-meta',
  },
] as const;
const CASES: { locale: AppLocale; width: number; text: number }[] = [
  ...[360, 412].flatMap((width) =>
    [110, 150, 200].map((text) => ({ locale: "sv" as const, width, text })),
  ),
  { locale: "en", width: 360, text: 200 },
];

for (const { view, tool, result, selector } of VIEWS)
  for (const { locale, width, text } of CASES)
    test(`${view} meta line at ${width} px, text ${text} %, ${locale}: the time and the status stand whole, the Project whole, cut with an ellipsis or left out`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(NOW);
      const { app, failures, networkRequests } = await openSimulatedApp(page, {
        resource: withRoboto(readBuiltApp("sidekick", locale)),
        width,
        height: 900,
        hostContext: {
          locale,
          theme: "light",
          platform: "mobile",
          displayMode: "fullscreen",
          availableDisplayModes: ["inline", "fullscreen"],
          toolInfo: { id: 1, tool: { name: tool } },
          styles: {
            variables: {
              "--font-sans": ROBOTO_STACK,
              "--sk-font": ROBOTO_STACK,
            },
          },
        },
        replies: {},
      });
      await waitForAppInitialized(page);
      await app
        .locator("html")
        .evaluate(
          (el, size) => ((el as HTMLElement).style.fontSize = size),
          `${text}%`,
        );
      await deliverToolResult(page, result);
      await expect(app.locator(selector).first()).toBeVisible();
      await settled(app);
      expect(
        await app.locator("html").evaluate(async (_el, family) => {
          await document.fonts.ready;
          return document.fonts.check(`400 16px '${family}'`);
        }, ROBOTO_FAMILY),
      ).toBe(true);
      const metas = await readMetas(app, selector);
      expect(metas.length).toBeGreaterThanOrEqual(3);
      const statusWords =
        locale === "sv" ? ["Pågår", "Blockerad"] : ["In progress", "Blocked"];
      for (const meta of metas) {
        const where = `${view} ${width}/${text} ${locale} «${meta.title}»: ${JSON.stringify(meta.parts)}`;
        for (const part of meta.parts) {
          if (part.cls.includes("work-card-project")) {
            // The Project: whole, left out whole, or cut with an ellipsis that leaves at least 4em (no stump).
            if (part.fit === "partial") {
              expect(part.ellipsis, where).toBe(true);
              expect(part.visibleEm, where).toBeGreaterThanOrEqual(3.9);
            }
          } else if (part.cls.includes("work-card-priority")) {
            // "Hög": whole or left out whole, never cut.
            expect(part.fit, where).not.toBe("partial");
            expect(part.ellipsis, where).toBe(false);
          } else {
            // The time, the status and the kind stand whole: never clipped, never wrapped out of sight.
            expect(part.fit, where).toBe("whole");
            expect(part.ellipsis, where).toBe(false);
          }
        }
        // The status words are on screen where the row has a status (not in Status, whose sections are the statuses).
        if (view === "Agenda") {
          const shown = meta.parts
            .filter((p) => p.cls.includes("work-card-status"))
            .map((p) => p.text);
          expect(
            shown.every((s) => statusWords.includes(s)),
            where,
          ).toBe(true);
          expect(shown.length, where).toBe(1);
        }
        // One meta line whenever the time, the status and the kind fit beside each other. Only at 200 % they may not
        // ("11 dagar försenad · Pågår" at 360 px, "· Blockerad" at 412 px): then the status takes a second line
        // rather than vanish, and never a third.
        if (meta.needs <= meta.width + 0.5) expect(meta.lines, where).toBe(1);
        else {
          expect(text, where).toBe(200);
          expect(meta.lines, where).toBe(2);
        }
        expect(meta.heightInLines, where).toBeCloseTo(meta.lines, 2);
        // The time stands first, on the first line.
        const due = meta.parts.find((p) => p.cls.includes("work-card-due"));
        if (due) expect(due, where).toBe(meta.parts[0]);
      }
      expect(failures).toEqual([]);
      expect(networkRequests()).toBe(0);
    });
