import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { box, buildSurface, type SurfaceBundle } from "./surface-bundle";

// The photo tiles (PhotoStrip, PhotoGrid) and the viewer (PhotoViewer) measured in a real Chromium. No view uses them
// yet, so the spec builds a test surface (photos-surface.tsx, see surface-bundle.ts) and loads it into a blank page: no
// host, no bridge, no backend. This is neither a Claude nor an Android test. PHOTOS_OUT=<dir> also writes the
// screenshots (light and dark, sv and en, inline 740/390/360/320, fullscreen 1440/412/390/360/320).

const OUT = process.env.PHOTOS_OUT ?? "";

let bundle: SurfaceBundle = { js: "", css: "" };

test.beforeAll(async () => {
  bundle = await buildSurface("photos-surface.tsx");
  if (OUT) mkdirSync(OUT, { recursive: true });
});

type Open = {
  scene: "card" | "day" | "entry" | "week" | "viewer";
  width: number;
  height?: number;
  locale?: "sv" | "en";
  theme?: "light" | "dark";
  extra?: Record<string, string>;
};

const SURFACE_CSS = `
html, body { margin: 0; background: var(--sk-bg); color: var(--sk-fg); font-family: var(--sk-font); }
.surface-full { display: grid; gap: var(--sk-s3); box-sizing: border-box; max-width: 48rem; margin: 0 auto;
  padding: var(--sk-s4); }
body[data-density="inline"] { padding: 20px; }
.surface-text { margin: 0; font: var(--sk-type-read); display: -webkit-box; -webkit-line-clamp: 3;
  -webkit-box-orient: vertical; overflow: hidden; }
.surface-heading { margin: 0; font: var(--sk-type-section); }
.surface-day { display: grid; gap: var(--sk-s2); }
`;

/** Loads the surface and returns the requests it made: there must be none (every image is a data: URL). */
async function open(page: Page, options: Open): Promise<string[]> {
  const { scene, width, locale = "sv", theme = "light" } = options;
  const density = scene === "card" ? "inline" : "full";
  await page.setViewportSize({ width, height: options.height ?? 800 });
  const requests: string[] = [];
  page.on("request", (request) => {
    if (!/^(?:data|about):/.test(request.url())) requests.push(request.url());
  });
  const data = Object.entries({ scene, locale, ...options.extra })
    .map(([key, value]) => ` data-${key}="${value}"`)
    .join("");
  await page.setContent(
    `<!doctype html><html lang="${locale}"${data} style="color-scheme: ${theme}"><head>` +
      `<meta charset="utf-8"><style>${bundle.css}\n${SURFACE_CSS}</style></head>` +
      `<body data-density="${density}"><div id="root"></div><script>${bundle.js}</script></body></html>`,
  );
  await expect(
    page.locator(".sk-photos, .sk-photo-viewer").first(),
  ).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  return requests;
}

/** Every tile's box. */
async function tiles(page: Page) {
  return Promise.all(
    (await page.locator(".sk-photo").all()).map((tile) => box(tile)),
  );
}

/** The element a tap at (x, y) reaches, by its photo id: so a tile's target can be measured past its drawn edge. */
async function hit(page: Page, x: number, y: number) {
  return page.evaluate(
    ([px, py]) =>
      document
        .elementFromPoint(px as number, py as number)
        ?.closest("[data-photo-id]")
        ?.getAttribute("data-photo-id") ?? null,
    [x, y],
  );
}

async function shot(page: Page, name: string, target?: Locator) {
  if (!OUT) return;
  await (target ?? page).screenshot({
    path: path.join(OUT, `${name}.png`),
    animations: "disabled",
  });
}

for (const locale of ["sv", "en"] as const)
  for (const width of [390, 360]) {
    test(`card inline (${locale}, ${width}): 64 tiles, the fourth "+3", under 340, no request`, async ({
      page,
    }) => {
      const requests = await open(page, { scene: "card", width, locale });
      const drawn = await tiles(page);
      expect(drawn).toHaveLength(4);
      for (const tile of drawn)
        expect([tile.width, tile.height]).toEqual([64, 64]);
      expect(drawn[1]!.x - (drawn[0]!.x + drawn[0]!.width)).toBe(8);
      const more = page.getByRole("button", {
        name: locale === "sv" ? "3 foton till" : "3 more photos",
      });
      await expect(more).toContainText("+3");
      // The strip with its air is 72.
      const strip = await box(page.locator(".sk-photos"));
      expect(strip.height).toBe(64);
      expect((await box(page.locator(".sk-card"))).height).toBeLessThan(340);
      // A caption that is only a file name gets the fallback name; nothing from the metadata reaches a tile.
      const names = await page
        .locator(".sk-photo img")
        .evaluateAll((imgs) => imgs.map((img) => img.getAttribute("alt")));
      expect(names[1]).toBe(
        locale === "sv" ? "Foto 2 från 14 nov" : "Photo 2 from 14 Nov",
      );
      expect(await page.locator(".sk-photos").textContent()).not.toMatch(
        /Visby|°|\d:\d/,
      );
      await page.locator(".sk-photo").first().click();
      await expect(page.getByTestId("opened")).toHaveText("p1");
      expect(requests).toEqual([]);
    });
  }

test("card inline on 320: the strip shrinks together, still square and above 44, never wraps", async ({
  page,
}) => {
  await open(page, { scene: "card", width: 320 });
  const drawn = await tiles(page);
  expect(new Set(drawn.map((tile) => tile.y)).size).toBe(1);
  for (const tile of drawn) {
    expect(tile.width).toBe(tile.height);
    expect(tile.width).toBeGreaterThanOrEqual(44);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

for (const width of [1440, 390]) {
  test(`day (${width}): 72 tiles fill at most two rows and the last is "+n"`, async ({
    page,
  }) => {
    const requests = await open(page, {
      scene: "day",
      width,
      extra: { count: "30" },
    });
    const drawn = await tiles(page);
    for (const tile of drawn)
      expect([tile.width, tile.height]).toEqual([72, 72]);
    const rows = [...new Set(drawn.map((tile) => tile.y))];
    expect(rows).toHaveLength(2);
    const grid = await box(page.locator(".sk-photos"));
    const perRow = Math.floor((grid.width + 8) / 80);
    expect(drawn).toHaveLength(perRow * 2);
    const hidden = 30 - (perRow * 2 - 1);
    await page.getByRole("button", { name: `${hidden} foton till` }).click();
    await expect(page.getByTestId("opened")).toHaveText("all");
    expect(requests).toEqual([]);
  });
}

test("entry: three columns on a phone, four on a desktop, square", async ({
  page,
}) => {
  await open(page, { scene: "entry", width: 390, extra: { count: "7" } });
  let drawn = await tiles(page);
  expect(drawn).toHaveLength(7);
  expect(drawn.filter((tile) => tile.y === drawn[0]!.y)).toHaveLength(3);
  for (const tile of drawn) expect(tile.width).toBe(tile.height);
  await open(page, { scene: "entry", width: 1440, extra: { count: "7" } });
  drawn = await tiles(page);
  expect(drawn.filter((tile) => tile.y === drawn[0]!.y)).toHaveLength(4);
});

test("week: 40 tiles that tap 44, '+n' after three", async ({ page }) => {
  const requests = await open(page, { scene: "week", width: 360 });
  const strips = page.locator(".sk-photos");
  await expect(strips).toHaveCount(3);
  const busy = strips.nth(1);
  const drawn = await Promise.all(
    (await busy.locator(".sk-photo").all()).map((tile) => box(tile)),
  );
  expect(drawn).toHaveLength(4);
  for (const tile of drawn) expect([tile.width, tile.height]).toEqual([40, 40]);
  await expect(
    busy.getByRole("button", { name: "4 foton till" }),
  ).toContainText("+4");
  // 2 past the drawn edge on every side still reaches the tile: a 44 target.
  const first = drawn[0]!;
  const id = await busy
    .locator(".sk-photo")
    .first()
    .getAttribute("data-photo-id");
  for (const [x, y] of [
    [first.x - 1.5, first.y + 20],
    [first.x + 20, first.y - 1.5],
    [first.x + 41.5, first.y + 20],
    [first.x + 20, first.y + 41.5],
  ])
    expect(await hit(page, x!, y!)).toBe(id);
  expect(requests).toEqual([]);
});

test("viewer: ← and → step, held at the ends, Esc closes; the steps and the fold are 48", async ({
  page,
}) => {
  const requests = await open(page, {
    scene: "viewer",
    width: 390,
    height: 844,
  });
  await expect(
    page.locator(".sk-photo-viewer__img:not(.sk-photo-viewer__img--preview)"),
  ).toBeVisible();
  const meta = page.locator(".sk-photo-viewer__meta");
  await expect(meta).toHaveText("1 av 6 · 14 nov 08:30 · Visby");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("current")).toHaveText("p1");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("current")).toHaveText("p2");
  await expect(meta).toHaveText("2 av 6 · 14 nov 09:05 · Visby");
  await page.keyboard.press("ArrowRight");
  // The third photo has coordinates only: no place on the meta line.
  await expect(meta).toHaveText("3 av 6 · 14 nov 10:30");
  for (const name of ["Föregående foto", "Nästa foto"]) {
    const step = await box(page.getByRole("button", { name }));
    expect([step.width, step.height]).toEqual([40, 40]);
  }
  const fold = page.getByRole("button", { name: /Fotodetaljer/ });
  expect((await box(fold)).height).toBeGreaterThanOrEqual(48);
  await fold.click();
  await expect(page.locator(".sk-photo-details dd").nth(1)).toHaveText(
    "57,6368° N, 18,2928° Ö",
  );
  for (let i = 0; i < 5; i += 1) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("current")).toHaveText("p6");
  await expect(
    page.getByRole("button", { name: "Nästa foto" }),
  ).toHaveAttribute("aria-disabled", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("closed")).toHaveText("1");
  expect(requests).toEqual([]);
});

test("viewer on a touch screen: a swipe to the left brings the next photo", async ({
  browser,
}) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 360, height: 740 },
  });
  const page = await context.newPage();
  await open(page, { scene: "viewer", width: 360, height: 740 });
  const stage = await box(page.locator(".sk-photo-viewer__stage"));
  const y = stage.y + stage.height / 2;
  await page.locator(".sk-photo-viewer__stage").dispatchEvent("pointerdown", {
    pointerType: "touch",
    pointerId: 7,
    clientX: stage.x + 250,
    clientY: y,
    isPrimary: true,
  });
  await page.locator(".sk-photo-viewer__stage").dispatchEvent("pointerup", {
    pointerType: "touch",
    pointerId: 7,
    clientX: stage.x + 100,
    clientY: y + 10,
    isPrimary: true,
  });
  await expect(page.getByTestId("current")).toHaveText("p2");
  await context.close();
});

test("viewer: a failed fetch keeps the thumbnail and offers Försök igen at 48", async ({
  page,
}) => {
  await open(page, { scene: "viewer", width: 360, extra: { fail: "true" } });
  await expect(page.getByText("Fotot kunde inte hämtas")).toBeVisible();
  const retry = await box(page.getByRole("button", { name: "Försök igen" }));
  expect(retry.height).toBeGreaterThanOrEqual(44);
  await expect(page.locator(".sk-photo-viewer__img--preview")).toBeVisible();
});

test("screenshots", async ({ page }) => {
  test.skip(!OUT, "PHOTOS_OUT is not set");
  test.setTimeout(300_000);
  for (const theme of ["light", "dark"] as const)
    for (const locale of ["sv", "en"] as const) {
      const tag = `${locale}-${theme}`;
      for (const width of [740, 390, 360, 320]) {
        await open(page, { scene: "card", width, locale, theme });
        await shot(page, `card-${width}-${tag}`, page.locator(".sk-card"));
      }
      for (const width of [1440, 390]) {
        await open(page, {
          scene: "day",
          width,
          locale,
          theme,
          height: 420,
          extra: { count: "30" },
        });
        await shot(page, `day-${width}-${tag}`);
      }
      await open(page, {
        scene: "entry",
        width: 390,
        locale,
        theme,
        height: 560,
        extra: { count: "7" },
      });
      await shot(page, `entry-390-${tag}`);
      await open(page, {
        scene: "week",
        width: 360,
        locale,
        theme,
        height: 360,
      });
      await shot(page, `week-360-${tag}`);
      for (const width of [1440, 412, 390, 360, 320]) {
        await open(page, {
          scene: "viewer",
          width,
          locale,
          theme,
          height: 900,
        });
        await expect(
          page.locator(
            ".sk-photo-viewer__img:not(.sk-photo-viewer__img--preview)",
          ),
        ).toBeVisible();
        await shot(page, `viewer-${width}-${tag}`);
        await page.locator(".sk-photo-details .sk-fold").click();
        await shot(page, `viewer-${width}-${tag}-details`);
      }
      await open(page, {
        scene: "viewer",
        width: 390,
        locale,
        theme,
        height: 900,
        extra: { fail: "true" },
      });
      await page.locator(".sk-error").waitFor();
      await shot(page, `viewer-390-${tag}-failed`);
      await open(page, {
        scene: "viewer",
        width: 360,
        locale,
        theme,
        height: 1100,
      });
      await page
        .locator("html")
        .evaluate((html) => (html.style.fontSize = "200%"));
      await page.locator(".sk-photo-details .sk-fold").click();
      await shot(page, `viewer-360-${tag}-details-200`);
    }
});
