import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { box, buildSurface, type SurfaceBundle } from "./surface-bundle";

// The review cards (FlipCard, QuestionCard) measured in a real Chromium. No view uses them yet, so the spec builds a
// test surface (review-cards-surface.tsx, see surface-bundle.ts) and loads it into a blank page: no host, no bridge, no
// backend. This is neither a Claude nor an Android test. REVIEW_CARDS_OUT=<dir> also writes the screenshots (light and
// dark, sv and en, inline 740/390/360 and fullscreen 1440/390/360).

const OUT = process.env.REVIEW_CARDS_OUT ?? "";

let bundle: SurfaceBundle = { js: "", css: "" };

test.beforeAll(async () => {
  bundle = await buildSurface("review-cards-surface.tsx");
  if (OUT) mkdirSync(OUT, { recursive: true });
});

type Open = {
  scene: "flip" | "flip-loading" | "flip-text" | "question";
  width: number;
  height?: number;
  locale?: "sv" | "en";
  theme?: "light" | "dark";
  density?: "inline" | "full";
  extra?: Record<string, string>;
};

const SURFACE_CSS = `
html, body { margin: 0; background: var(--sk-bg); color: var(--sk-fg); font-family: var(--sk-font); }
.surface-full { display: grid; gap: var(--sk-s5); box-sizing: border-box; max-width: 48rem; margin: 0 auto;
  padding: var(--sk-s4); }
body[data-density="inline"] { padding: 20px; }
`;

/** Loads the surface and returns the requests it made: there must be none. */
async function open(page: Page, options: Open): Promise<string[]> {
  const { scene, width, locale = "sv", theme = "light" } = options;
  const density = options.density ?? "full";
  await page.setViewportSize({ width, height: options.height ?? 800 });
  const requests: string[] = [];
  page.on("request", (request) => {
    if (!/^(?:data|about):/.test(request.url())) requests.push(request.url());
  });
  const data = Object.entries({
    scene,
    locale,
    density,
    ...options.extra,
  })
    .map(([key, value]) => ` data-${key}="${value}"`)
    .join("");
  await page.setContent(
    `<!doctype html><html lang="${locale}"${data} style="color-scheme: ${theme}"><head>` +
      `<meta charset="utf-8"><style>${bundle.css}\n${SURFACE_CSS}</style></head>` +
      `<body data-density="${density}"><div id="root"></div><script>${bundle.js}</script></body></html>`,
  );
  await expect(page.locator(".sk-flip, .sk-question").first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  return requests;
}

async function shot(page: Page, name: string, target?: Locator) {
  if (!OUT) return;
  await (target ?? page).screenshot({
    path: path.join(OUT, `${name}.png`),
    animations: "disabled",
  });
}

const names = {
  sv: {
    card: "Repetitionskort",
    reveal: "Visa svaret",
    again: "Igen",
    good: "Kunde",
  },
  en: {
    card: "Review card",
    reveal: "Show the answer",
    again: "Again",
    good: "Got it",
  },
} as const;

for (const locale of ["sv", "en"] as const) {
  for (const width of [390, 360]) {
    test(`inline (${locale}, ${width}): the card stays under 340 and keeps its height when it turns`, async ({
      page,
    }) => {
      const requests = await open(page, {
        scene: "flip",
        width,
        locale,
        density: "inline",
      });
      const card = page.locator(".sk-card");
      const before = await box(card);
      expect(before.height).toBeLessThan(340);
      const face = await box(page.locator(".sk-flip__face"));
      expect([face.width, face.height]).toEqual([120, 120]);

      await page.getByRole("button", { name: names[locale].reveal }).click();
      await expect(page.locator(".sk-flip__answer")).toBeFocused();
      const after = await box(card);
      expect(after.height).toBe(before.height);
      for (const label of [names[locale].again, names[locale].good])
        expect(
          (await box(page.getByRole("button", { name: label }))).height,
        ).toBeGreaterThanOrEqual(48);
      expect(requests).toEqual([]);

      // The owner's phone draws text at about 110 %: still under 340.
      await page
        .locator("html")
        .evaluate((html) => (html.style.fontSize = "110%"));
      expect((await box(card)).height).toBeLessThan(340);
    });
  }
}

test("fullscreen on 360: one thumb reaches everything, the grades stand where the reveal stood, no scroll", async ({
  page,
}) => {
  // Measured without the answer's rise, which moves the back side 4 px while it runs.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page, { scene: "flip", width: 360, height: 740 });
  const face = await box(page.locator(".sk-flip__face"));
  expect([face.width, face.height]).toEqual([200, 200]);
  const flip = await box(page.locator(".sk-flip"));
  const reveal = await box(page.getByRole("button", { name: "Visa svaret" }));
  expect(reveal.height).toBe(48);
  expect(reveal.width).toBe(flip.width);

  await page.getByRole("button", { name: "Visa svaret" }).click();
  const again = await box(page.getByRole("button", { name: "Igen" }));
  const good = await box(page.getByRole("button", { name: "Kunde" }));
  expect(await box(page.locator(".sk-flip"))).toEqual(flip);
  for (const grade of [again, good]) {
    expect(grade.height).toBe(48);
    // Each grade is a thumb-wide half of the row, side by side on the reveal button's line.
    expect(grade.width).toBeGreaterThanOrEqual((flip.width - 8) / 2 - 1);
    expect(grade.bottom).toBe(reveal.bottom);
    expect(grade.bottom).toBeLessThanOrEqual(740);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight <= window.innerHeight,
    ),
  ).toBe(true);
});

test("the keys: Space turns, 2 grades Kunde, the next card takes the focus to its reveal", async ({
  page,
}) => {
  await open(page, { scene: "flip", width: 390 });
  await page.getByRole("group", { name: "Repetitionskort" }).focus();
  const photo = await page.locator(".sk-flip__photo").getAttribute("src");
  await page.keyboard.press("Space");
  await expect(page.locator(".sk-flip__answer")).toBeFocused();
  await expect(page.locator(".sk-flip__answer")).toContainText("Lena Holm");
  await page.keyboard.press("2");
  await expect(page.getByTestId("grades")).toHaveText("good");
  await expect(page.getByRole("button", { name: "Visa svaret" })).toBeFocused();
  expect(await page.locator(".sk-flip__photo").getAttribute("src")).not.toBe(
    photo,
  );
  await page.keyboard.press("Enter");
  await page.keyboard.press("1");
  await expect(page.getByTestId("grades")).toHaveText("good,again");
});

test("motion: the answer rises in, and not at all under reduced motion", async ({
  page,
}) => {
  await open(page, { scene: "flip", width: 390 });
  await page.getByRole("button", { name: "Visa svaret" }).click();
  const back = page.locator(".sk-flip__side--back");
  expect(
    await back.evaluate((node) => getComputedStyle(node).animationName),
  ).toBe("sk-flip-rise");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page, { scene: "flip", width: 390 });
  await page.getByRole("button", { name: "Visa svaret" }).click();
  expect(
    await back.evaluate((node) => {
      const style = getComputedStyle(node);
      return [style.animationName, style.opacity, style.transform];
    }),
  ).toEqual(["none", "1", "none"]);
});

test("loading: the face is a skeleton and the reveal is held", async ({
  page,
}) => {
  await open(page, { scene: "flip-loading", width: 390 });
  await expect(page.locator(".sk-flip__skeleton")).toBeVisible();
  const reveal = page.getByRole("button", { name: "Visa svaret" });
  await expect(reveal).toHaveAttribute("aria-disabled", "true");
  // aria-disabled keeps the focus on the button; Playwright counts it as disabled, so the press is forced.
  await reveal.click({ force: true });
  await expect(page.locator(".sk-flip__side--back")).toHaveAttribute(
    "aria-hidden",
    "true",
  );
});

test("question on 360: 48 high options, a wrong answer is asked again, the focus comes back to the first option", async ({
  page,
}) => {
  await open(page, { scene: "question", width: 360 });
  const options = page.locator(".sk-question__option");
  await expect(options).toHaveCount(4);
  for (const option of await options.all())
    expect((await box(option)).height).toBeGreaterThanOrEqual(48);

  await options.first().focus();
  await page.keyboard.press("1");
  await expect(page.getByRole("status")).toContainText("Inte riktigt.");
  const retry = page.getByRole("button", { name: "Försök igen" });
  expect((await box(retry)).height).toBe(48);
  await retry.click();
  await expect(options.first()).toBeFocused();
  await page.keyboard.press("2");
  await expect(page.getByRole("status")).toContainText("Rätt.");
  await expect(page.getByRole("button", { name: "Nästa" })).toBeVisible();
});

test("screenshots", async ({ page }) => {
  test.skip(!OUT, "REVIEW_CARDS_OUT is not set");
  test.setTimeout(240_000);
  for (const theme of ["light", "dark"] as const)
    for (const locale of ["sv", "en"] as const) {
      for (const width of [740, 390, 360]) {
        await open(page, {
          scene: "flip",
          width,
          locale,
          theme,
          density: "inline",
        });
        const card = page.locator(".sk-card");
        await shot(page, `inline-${width}-${locale}-${theme}-front`, card);
        await page.getByRole("button", { name: names[locale].reveal }).click();
        await page.locator("body").click({ position: { x: 1, y: 1 } });
        await shot(page, `inline-${width}-${locale}-${theme}-back`, card);
      }
      for (const width of [1440, 390, 360]) {
        await open(page, { scene: "flip", width, locale, theme, height: 740 });
        await shot(page, `full-${width}-${locale}-${theme}-front`);
        await page.getByRole("group", { name: names[locale].card }).focus();
        await page.keyboard.press("Space");
        await shot(page, `full-${width}-${locale}-${theme}-back-keyboard`);
      }
      // Large text (200 %): the card grows but nothing is cut or overlaps.
      await open(page, {
        scene: "flip",
        width: 360,
        locale,
        theme,
        density: "inline",
        extra: { revealed: "true" },
      });
      await page
        .locator("html")
        .evaluate((html) => (html.style.fontSize = "200%"));
      await shot(
        page,
        `inline-360-${locale}-${theme}-back-200`,
        page.locator(".sk-card"),
      );
      await open(page, {
        scene: "flip-text",
        width: 390,
        locale,
        theme,
        density: "inline",
      });
      await shot(
        page,
        `inline-390-${locale}-${theme}-text`,
        page.locator(".sk-card"),
      );
      await open(page, { scene: "flip-loading", width: 390, locale, theme });
      await shot(page, `full-390-${locale}-${theme}-loading`);
      for (const [label, extra] of [
        ["open", {}],
        ["checking", { chosen: "1", checking: "true" }],
        ["right", { chosen: "1" }],
        ["wrong", { chosen: "0" }],
        ["offline", { offline: "true" }],
      ] as const) {
        await open(page, {
          scene: "question",
          width: 390,
          locale,
          theme,
          height: 640,
          extra,
        });
        await shot(page, `question-390-${locale}-${theme}-${label}`);
      }
      await open(page, {
        scene: "question",
        width: 1440,
        locale,
        theme,
        height: 640,
        extra: { chosen: "1" },
      });
      await shot(page, `question-1440-${locale}-${theme}-right`);
    }
});
