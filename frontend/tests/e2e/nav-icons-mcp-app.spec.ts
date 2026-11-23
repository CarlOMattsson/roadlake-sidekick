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

// What the room strip draws (SIDEKICK_MCP_APP_NAV_ICONS, nav-icons.ts). By default (`auto`) the names alone where the
// frame has room for them, and a glyph over each name in a phone's frame; or the names alone (`off`), a glyph before
// each name (`label`), or the glyphs alone (`only`). Measured on the simulated host (mcp-host-fixture.ts), which is not
// a real Claude or Android host. The strip is one row of 40, except in a phone's frame with a glyph over each name
// (`auto`, `label`), where it is 48 to hold the targets. Every cell keeps its target, and a cell that draws no name is
// named for assistive technology and in a tooltip.

type Mode = "auto" | "off" | "label" | "only";

async function open(
  page: Page,
  options: { mode: Mode; width: number; locale: AppLocale; height?: number },
): Promise<FrameLocator> {
  const built = readBuiltApp("sidekick", options.locale);
  const { app } = await openSimulatedApp(page, {
    // As the backend declares it: no meta at all for the default.
    resource:
      options.mode === "auto"
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
  glyphShown: boolean;
  nameShown: boolean;
  nameWidth: number;
};

/** The strip as drawn: its box, whether the room picker took its place, and every cell with its Mer cell last. */
function measure(app: FrameLocator) {
  return app.locator("nav.sk-rooms").evaluate((strip) => {
    const tabs = strip.querySelector(".sk-rooms__tabs")!;
    const cells: Cell[] = Array.from(
      strip.querySelectorAll<HTMLElement>(".sk-rooms__tab"),
      (cell) => {
        const name = cell.querySelector<HTMLElement>(".sk-rooms__name");
        const isMore = cell.classList.contains("sk-rooms__more");
        // The room's glyph: the svg that comes right before its name, or else the first svg of a cell with no name
        // (`only`), where Mer's ⌄ is the last one.
        const glyph =
          cell.querySelector("svg:has(+ .sk-rooms__name)") ??
          (cell.querySelectorAll("svg").length > (isMore ? 1 : 0)
            ? cell.querySelector("svg")
            : null);
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
          glyphShown: glyph !== null && glyph.getClientRects().length > 0,
          nameShown: name !== null && name.getClientRects().length > 0,
          nameWidth: name === null ? 0 : name.getBoundingClientRect().width,
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
    test(`names alone: one row of 40 at ${width} px in ${locale}`, async ({
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

    test(`the default draws a glyph over each name: one row of 48 at ${width} px in ${locale}`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "auto", width, locale }),
      );
      expect(strip.icons).toBe("auto");
      expect(strip.picker).toBe(false);
      expect(strip.overflow).toBeLessThanOrEqual(0);
      expect(strip.height).toBe(48);
      expect(strip.cells.map((cell) => cell.text)).toEqual(NAMES[locale]);
      for (const cell of strip.cells) {
        expect(cell.label).toBeNull();
        expect(cell.title).toBeNull();
        expect(cell.glyphs[0]).toEqual({ width: 20, height: 20 });
        expect(cell.glyphShown).toBe(true);
        expect(cell.nameShown).toBe(true);
        expect(cell.width).toBeGreaterThanOrEqual(44);
        expect(cell.targetHeight).toBe(56);
        expect(cell.nameWidth).toBeLessThanOrEqual(cell.width);
      }
    });

    test(`a glyph with the name: one row of 48 at ${width} px in ${locale}, every cell named`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "label", width, locale }),
      );
      expect(strip.icons).toBe("label");
      expect(strip.picker).toBe(false);
      expect(strip.overflow).toBeLessThanOrEqual(0);
      expect(strip.height).toBe(48);
      // Every cell is named, and every name is drawn under its glyph.
      expect(strip.cells.map((cell) => cell.label)).toEqual(NAMES[locale]);
      expect(strip.cells.map((cell) => cell.text)).toEqual(NAMES[locale]);
      for (const cell of strip.cells) {
        expect(cell.title).toBeNull();
        expect(cell.glyphs[0]).toEqual({ width: 20, height: 20 });
        expect(cell.glyphShown).toBe(true);
        expect(cell.nameShown).toBe(true);
        expect(cell.width).toBeGreaterThanOrEqual(44);
        expect(cell.targetHeight).toBe(56);
        expect(cell.nameWidth).toBeLessThanOrEqual(cell.width);
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

test("the default: a room of Mer that is open is named in the Mer cell", async ({
  page,
}) => {
  const app = await open(page, { mode: "auto", width: 360, locale: "sv" });
  const more = app.locator(".sk-rooms__more");
  await more.click();
  await app
    .getByRole("group", { name: "Fler rum", exact: true })
    .getByRole("button", { name: "Kontakter", exact: true })
    .click();
  await settled(app);
  await expect(more).toHaveAttribute("aria-current", "page");
  await expect(more).toHaveAttribute("aria-label", "Kontakter, Mer");
  await expect(more).not.toHaveAttribute("title");
  const strip = await measure(app);
  expect(strip.height).toBe(48);
  expect(strip.picker).toBe(false);
});

test("opening Mer turns its ⌄ and leaves the room's glyph", async ({
  page,
}) => {
  const app = await open(page, { mode: "label", width: 360, locale: "sv" });
  const more = app.locator(".sk-rooms__more");
  await more.click();
  await settled(app);
  // The glyph is the cell's first svg, the ⌄ its last; only the ⌄ turns.
  await expect
    .poll(async () =>
      more
        .locator("svg")
        .last()
        .evaluate((svg) => getComputedStyle(svg).transform),
    )
    .not.toBe("none");
  const glyphTransform = await more
    .locator("svg")
    .first()
    .evaluate((svg) => getComputedStyle(svg).transform);
  expect(glyphTransform).toBe("none");
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

test("large text: the default draws the names alone, as high as names alone are", async ({
  page,
}) => {
  // 390 px at 150 % text is a frame of 16.25 rem: the names are large enough alone, and the chrome keeps its bound.
  const large = async (mode: Mode) => {
    const app = await open(page, { mode, width: 390, locale: "sv" });
    await app
      .locator("html")
      .evaluate((root) => (root.style.fontSize = "24px"));
    await settled(app);
    return measure(app);
  };
  const auto = await large("auto");
  const off = await large("off");
  expect(auto.icons).toBe("auto");
  expect(auto.height).toBe(off.height);
  expect(auto.picker).toBe(off.picker);
  for (const cell of auto.cells) {
    expect(cell.glyphShown).toBe(false);
    expect(cell.nameShown).toBe(!auto.picker);
  }
});

test("a wide frame: the default draws the names alone, cell for cell as names alone do", async ({
  page,
}) => {
  const auto = await measure(
    await open(page, { mode: "auto", width: 1280, height: 800, locale: "en" }),
  );
  const off = await measure(
    await open(page, { mode: "off", width: 1280, height: 800, locale: "en" }),
  );
  expect(auto.height).toBe(40);
  expect(off.height).toBe(40);
  expect(auto.cells.map((cell) => cell.width)).toEqual(
    off.cells.map((cell) => cell.width),
  );
  for (const cell of auto.cells) {
    expect(cell.glyphShown).toBe(false);
    expect(cell.nameShown).toBe(true);
  }
  expect(auto.cells.map((cell) => cell.text)).toEqual(NAMES.en);
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

const HOME: Record<AppLocale, string> = { sv: "Start", en: "Home" };

for (const locale of ["sv", "en"] as const) {
  test(`a row of five holds at 360 px in ${locale}`, async ({ page }) => {
    const app = await open(page, { mode: "auto", width: 360, locale });
    // The row is dimensioned for five cells: four rooms and Mer. A fifth room cell is put in first.
    const row = await app.locator(".sk-rooms__tabs").evaluate((tabs, home) => {
      const source = Array.from(
        tabs.querySelectorAll<HTMLElement>(".sk-rooms__tab"),
      ).find(
        (cell) =>
          cell.getAttribute("aria-current") !== "page" &&
          !cell.classList.contains("sk-rooms__more"),
      )!;
      const extra = source.cloneNode(true) as HTMLElement;
      extra.querySelector(".sk-rooms__name")!.textContent = home;
      tabs.prepend(extra);
      return {
        overflow: tabs.scrollWidth - tabs.clientWidth,
        names: Array.from(tabs.querySelectorAll(".sk-rooms__name"), (name) => ({
          name: name.getBoundingClientRect().width,
          cell: name.closest(".sk-rooms__tab")!.getBoundingClientRect().width,
        })),
      };
    }, HOME[locale]);
    expect(row.overflow).toBeLessThanOrEqual(0);
    for (const name of row.names) {
      expect(name.name).toBeLessThanOrEqual(name.cell);
    }
  });
}

const AXE_STRIPS: Record<Exclude<Mode, "off">, string> = {
  auto: "the default strip",
  label: "a strip of glyphs and names",
  only: "a strip of glyphs alone",
};

for (const mode of ["auto", "label", "only"] as const) {
  test(`axe finds no WCAG A/AA violation in ${AXE_STRIPS[mode]}`, async ({
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
