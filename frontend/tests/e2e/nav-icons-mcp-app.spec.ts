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

// What the room strip draws (SIDEKICK_MCP_APP_NAV_ICONS, nav-icons.ts). By default (`auto`) a phone's frame at an
// ordinary text size draws a glyph before the name of the open room, and every other frame the names alone. The other
// three modes are the same at every width: the names alone (`off`), a glyph before each name (`label`), or the glyphs
// alone (`only`). Measured on the simulated host (mcp-host-fixture.ts), which is not a real Claude or Android host. At
// the phone and wide widths measured here the strip is one row of 40 in every mode, and every cell keeps its target. A
// cell that draws no name is named for assistive technology and in a tooltip.

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

type Strip = Awaited<ReturnType<typeof measure>>;

const NAMES: Record<AppLocale, string[]> = {
  sv: ["Start", "Arbete", "Dagbok", "Inköp", "Mer"],
  en: ["Home", "Work", "Journal", "Shopping", "More"],
};

/**
 * A strip with a glyph before every room's name, in a phone's frame at an ordinary text size: the open room's name is
 * drawn and the others are named by their tooltips. Each cell keeps its target and its glyph.
 */
function expectGlyphsAndOpenName(strip: Strip, names: string[]) {
  expect(strip.picker).toBe(false);
  expect(strip.overflow).toBeLessThanOrEqual(0);
  expect(strip.height).toBe(40);
  expect(strip.cells.map((cell) => cell.label)).toEqual(names);
  expect(strip.cells.filter((cell) => cell.current)).toHaveLength(1);
  strip.cells.forEach((cell, index) => {
    expect(cell.glyphs[0]).toEqual({ width: 20, height: 20 });
    expect(cell.glyphShown).toBe(true);
    expect(cell.nameShown).toBe(cell.current);
    expect(cell.width).toBeGreaterThanOrEqual(44);
    expect(cell.targetHeight).toBe(48);
    expect(cell.nameWidth).toBeLessThanOrEqual(cell.width);
    expect(cell.title).toBe(cell.current ? null : names[index]);
  });
}

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
        0, 0, 0, 0, 1,
      ]);
    });

    test(`the default draws glyphs and names the open room: one row of 40 at ${width} px in ${locale}`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "auto", width, locale }),
      );
      expect(strip.icons).toBe("label");
      expectGlyphsAndOpenName(strip, NAMES[locale]);
    });

    test(`a glyph before the name: one row of 40 at ${width} px in ${locale}, every cell named`, async ({
      page,
    }) => {
      const strip = await measure(
        await open(page, { mode: "label", width, locale }),
      );
      expect(strip.icons).toBe("label");
      expectGlyphsAndOpenName(strip, NAMES[locale]);
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
  // The cell draws its room's name now, so it has no tooltip left (the attribute may stay, empty).
  expect((await more.getAttribute("title")) ?? "").toBe("");
  await expect(more.locator(".sk-rooms__name")).toBeVisible();
  const strip = await measure(app);
  expect(strip.height).toBe(40);
  expect(strip.picker).toBe(false);
  // The four rooms that are not open are named by their tooltips.
  expect(strip.cells.slice(0, 4).map((cell) => cell.title)).toEqual(
    NAMES.sv.slice(0, 4),
  );
});

for (const locale of ["sv", "en"] as const) {
  for (const width of [390, 360, 320]) {
    test(`the default: the strip stays where it is when another room opens at ${width} px in ${locale}`, async ({
      page,
    }) => {
      const app = await open(page, { mode: "auto", width, locale });
      const strip = app.locator("nav.sk-rooms");
      const box = () =>
        strip.evaluate((nav) => {
          const { x, y, width: w, height } = nav.getBoundingClientRect();
          return { x, y, width: w, height };
        });
      const before = await box();
      // Dagbok or Journal, then Inköp or Shopping: each one opens in turn (Work is open at first).
      for (const index of [2, 3]) {
        await strip
          .getByRole("button", { name: NAMES[locale][index], exact: true })
          .click();
        await settled(app);
        expect(await box()).toEqual(before);
        const measured = await measure(app);
        expect(measured.picker).toBe(false);
        expect(measured.overflow).toBeLessThanOrEqual(0);
        expect(measured.height).toBe(40);
        expect(measured.cells.map((cell) => cell.current)).toEqual(
          [0, 1, 2, 3, 4].map((i) => i === index),
        );
        expect(measured.cells[index]?.nameShown).toBe(true);
        expect(measured.cells[index]?.text).toBe(NAMES[locale][index]);
      }
    });
  }
}

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
  expect(alone.cells.map((cell) => cell.width)).toEqual([48, 48, 48, 48, 48]);

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
  expect(auto.icons).toBeNull();
  expect(auto.height).toBe(off.height);
  expect(auto.picker).toBe(off.picker);
  expect(auto.cells.map((cell) => cell.text)).toEqual(
    off.cells.map((cell) => cell.text),
  );
  for (const cell of auto.cells) {
    expect(cell.glyphShown).toBe(false);
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
  expect(auto.icons).toBeNull();
  expect(auto.height).toBe(40);
  expect(off.height).toBe(40);
  expect(auto.cells.map((cell) => cell.width)).toEqual(
    off.cells.map((cell) => cell.width),
  );
  // Only Mer's ⌄ is drawn, and no cell is named by a label or a tooltip.
  expect(auto.cells.map((cell) => cell.glyphs.length)).toEqual([0, 0, 0, 0, 1]);
  for (const cell of auto.cells) {
    expect(cell.glyphShown).toBe(false);
    expect(cell.label).toBeNull();
    expect(cell.title).toBeNull();
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
    false,
    true,
    false,
  ]);
  expect(after.cells.map((cell) => cell.width)).toEqual(before);
});

/**
 * The strip at its capacity: four rooms of their own and Mer make a row of five. The row must hold at 360 px, with
 * every cell at least a touch target wide and no name wider than its cell.
 */
async function expectRowOfFive(app: FrameLocator) {
  const row = await app.locator(".sk-rooms__tabs").evaluate((tabs) => ({
    overflow: tabs.scrollWidth - tabs.clientWidth,
    widths: Array.from(
      tabs.querySelectorAll<HTMLElement>(".sk-rooms__tab"),
      (cell) => cell.getBoundingClientRect().width,
    ),
    names: Array.from(
      tabs.querySelectorAll<HTMLElement>(".sk-rooms__name"),
      (name) => ({
        name: name.getBoundingClientRect().width,
        cell: name.closest(".sk-rooms__tab")!.getBoundingClientRect().width,
      }),
    ),
  }));
  expect(row.widths).toHaveLength(5);
  expect(row.overflow).toBeLessThanOrEqual(0);
  for (const width of row.widths) {
    expect(width).toBeGreaterThanOrEqual(44);
  }
  for (const name of row.names) {
    expect(name.name).toBeLessThanOrEqual(name.cell);
  }
}

for (const locale of ["sv", "en"] as const) {
  test(`a row of five holds at 360 px in ${locale}`, async ({ page }) => {
    const app = await open(page, { mode: "auto", width: 360, locale });
    await expectRowOfFive(app);
  });

  test(`a row of five holds at 360 px in ${locale} with the widest room open`, async ({
    page,
  }) => {
    const app = await open(page, { mode: "auto", width: 360, locale });
    // Inköp or Shopping, the room whose name is the widest of the four.
    await app
      .locator("nav.sk-rooms")
      .getByRole("button", { name: NAMES[locale][3], exact: true })
      .click();
    await settled(app);
    await expectRowOfFive(app);
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
