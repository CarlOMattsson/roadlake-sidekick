import AxeBuilder from "@axe-core/playwright";
import { expect, test, type FrameLocator, type Page } from "@playwright/test";
import { domainReplies, opening } from "./sidekick-domain-fixtures";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
  type AppLocale,
} from "./mcp-host-fixture";

// What the room strip draws (SIDEKICK_MCP_APP_NAV_ICONS, nav-icons.ts): names alone (the default), a glyph before
// each name, or the glyphs alone. Measured on the simulated host (mcp-host-fixture.ts), which is not a real Claude or
// Android host: the strip stays one row of 40 in every mode, also at 360 px in English, every cell keeps its target,
// and a cell that draws no name is named for assistive technology and in a tooltip.

type Mode = "off" | "label" | "only";

async function open(
  page: Page,
  options: { mode: Mode; width: number; locale: AppLocale; height?: number },
): Promise<FrameLocator> {
  const built = readBuiltApp("sidekick", options.locale);
  const { app } = await openSimulatedApp(page, {
    // As the backend declares it: no meta at all for the default.
    resource:
      options.mode === "off"
        ? built
        : built.replace(
            "<head>",
            `<head><meta name="sidekick-nav-icons" content="${options.mode}">`,
          ),
    width: options.width,
    height: options.height ?? 780,
    hostContext: {
      locale: "sv",
      theme: "light",
      platform: options.width >= 1024 ? "desktop" : "mobile",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: "get_work_board" } },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: domainReplies(),
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, opening.workBoard);
  await settled(app);
  return app;
}

type Cell = {
  text: string;
  label: string | null;
  title: string | null;
  current: boolean;
  width: number;
  targetHeight: number;
  glyphs: { width: number; height: number }[];
  nameShown: boolean;
};

/** The strip as drawn: its box, whether the room picker took its place, and every cell with its Mer cell last. */
function measure(app: FrameLocator) {
  return app.locator("nav.sk-rooms").evaluate((strip) => {
    const tabs = strip.querySelector(".sk-rooms__tabs")!;
    const cells: Cell[] = Array.from(
      strip.querySelectorAll<HTMLElement>(".sk-rooms__tab"),
      (cell) => {
        const name = cell.querySelector<HTMLElement>(".sk-rooms__name");
        return {
          text: cell.textContent ?? "",
          label: cell.getAttribute("aria-label"),
          title: cell.getAttribute("title"),
          current: cell.getAttribute("aria-current") === "page",
          width: cell.getBoundingClientRect().width,
          targetHeight: parseFloat(getComputedStyle(cell, "::after").height),
          glyphs: Array.from(cell.querySelectorAll("svg"), (svg) => {
            const box = svg.getBoundingClientRect();
            return { width: box.width, height: box.height };
          }),
          nameShown: name !== null && name.getClientRects().length > 0,
        };
      },
    );
    return {
      height: strip.getBoundingClientRect().height,
      icons: strip.getAttribute("data-icons"),
      picker: tabs.hasAttribute("data-narrow"),
      overflow: tabs.scrollWidth - tabs.clientWidth,
      cells,
    };
  });
}

const NAMES: Record<AppLocale, string[]> = {
  sv: ["Arbete", "Dagbok", "Inköp", "Mer"],
  en: ["Work", "Journal", "Shopping", "More"],
};

for (const locale of ["sv", "en"] as const) {
  for (const width of [360, 320]) {
    test(`names alone are the default: one row of 40 at ${width} px in ${locale}`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "off", width, locale }),
      );
      expect(strip.icons).toBeNull();
      expect(strip.picker).toBe(false);
      expect(strip.height).toBe(40);
      expect(strip.cells.map((cell) => cell.text)).toEqual(NAMES[locale]);
      for (const cell of strip.cells) {
        expect(cell.label).toBeNull();
        expect(cell.title).toBeNull();
        expect(cell.targetHeight).toBe(48);
      }
      // No room glyph: only the Mer cell's ⌄.
      expect(strip.cells.map((cell) => cell.glyphs.length)).toEqual([
        0, 0, 0, 1,
      ]);
    });

    test(`a glyph before the name: one row of 40 at ${width} px in ${locale}, the open room named`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "label", width, locale }),
      );
      expect(strip.icons).toBe("label");
      expect(strip.picker).toBe(false);
      expect(strip.overflow).toBeLessThanOrEqual(0);
      expect(strip.height).toBe(40);
      // Every cell is named, whether its name is drawn or not.
      expect(strip.cells.map((cell) => cell.label)).toEqual(NAMES[locale]);
      for (const cell of strip.cells) {
        expect(cell.glyphs[0]).toEqual({ width: 20, height: 20 });
        expect(cell.width).toBeGreaterThanOrEqual(44);
        expect(cell.targetHeight).toBe(48);
        // A phone's frame draws the name in the room that is open and the glyph alone in the others.
        expect(cell.nameShown).toBe(cell.current);
      }
      expect(strip.cells.filter((cell) => cell.current)).toHaveLength(1);
    });

    test(`glyphs alone: one row of 40 at ${width} px in ${locale}, every cell named and with a tooltip`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "only", width, locale }),
      );
      expect(strip.icons).toBe("only");
      expect(strip.picker).toBe(false);
      expect(strip.overflow).toBeLessThanOrEqual(0);
      expect(strip.height).toBe(40);
      expect(strip.cells.map((cell) => cell.label)).toEqual(NAMES[locale]);
      expect(strip.cells.map((cell) => cell.title)).toEqual(NAMES[locale]);
      for (const cell of strip.cells) {
        expect(cell.text).toBe("");
        expect(cell.glyphs[0]).toEqual({ width: 20, height: 20 });
        expect(cell.width).toBeGreaterThanOrEqual(44);
        expect(cell.targetHeight).toBe(48);
      }
    });
  }
}

test("glyphs alone: a room of Mer that is open keeps its own glyph, name and tooltip", async ({
  page,
}) => {
  const app = await open(page, { mode: "only", width: 360, locale: "sv" });
  const more = app.locator(".sk-rooms__more");
  await more.click();
  await app
    .getByRole("group", { name: "Fler rum", exact: true })
    .getByRole("button", { name: "Kontakter", exact: true })
    .click();
  await settled(app);
  await expect(more).toHaveAttribute("aria-current", "page");
  await expect(more).toHaveAttribute("aria-label", "Kontakter, Mer");
  await expect(more).toHaveAttribute("title", "Kontakter");
  const strip = await measure(app);
  expect(strip.height).toBe(40);
  expect(strip.picker).toBe(false);
});

test("a wide frame: glyphs alone are cells of 48, and a glyph before the name keeps every name", async ({
  page,
}) => {
  const alone = await measure(
    await open(page, { mode: "only", width: 1280, height: 800, locale: "en" }),
  );
  expect(alone.height).toBe(40);
  expect(alone.cells.map((cell) => cell.width)).toEqual([48, 48, 48, 48]);

  const named = await measure(
    await open(page, { mode: "label", width: 1280, height: 800, locale: "en" }),
  );
  expect(named.height).toBe(40);
  expect(named.cells.map((cell) => cell.text)).toEqual(NAMES.en);
  expect(named.cells.every((cell) => cell.nameShown)).toBe(true);
});

test("a wide frame: opening another room moves no cell of a strip with glyphs and names", async ({
  page,
}) => {
  const app = await open(page, {
    mode: "label",
    width: 1280,
    height: 800,
    locale: "sv",
  });
  const before = (await measure(app)).cells.map((cell) => cell.width);
  await app
    .locator("nav.sk-rooms")
    .getByRole("button", { name: "Inköp", exact: true })
    .click();
  await settled(app);
  const after = await measure(app);
  expect(after.cells.map((cell) => cell.current)).toEqual([
    false,
    false,
    true,
    false,
  ]);
  expect(after.cells.map((cell) => cell.width)).toEqual(before);
});

for (const mode of ["label", "only"] as const) {
  test(`axe finds no WCAG A/AA violation in a strip of ${mode === "only" ? "glyphs alone" : "glyphs and names"}`, async ({
    page,
  }) => {
    // axe measures every text run; the one slow step here, as in a11y-axe-mcp-app.spec.ts.
    test.slow();
    const app = await open(page, { mode, width: 390, locale: "sv" });
    // The app's root is transparent: a real host paints the page, the simulated one does not.
    await app
      .locator("html")
      .evaluate((root) => (root.style.backgroundColor = "#ffffff"));
    const results = await new AxeBuilder({ page })
      .include("iframe")
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map((violation) => ({
        rule: violation.id,
        targets: violation.nodes.map((node) => node.target.join(" ")),
      })),
    ).toEqual([]);
  });
}
