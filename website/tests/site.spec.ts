import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';
import { base, budget, distDir, exists, largest, smallTargets, trackCspViolations, trackNetwork } from './helpers';

// Site-wide checks (teknik.md 5.2, 5.6, 5.7): accessibility, hit areas, no external requests, no cookies, CSP,
// byte budget, keyboard order, search and language switching. Everything runs against dist/ served by scripts/serve-dist.mjs.
// This is a simulated browser run of the built site, not a test on a real phone.

const origin = 'http://localhost:4321';
test.describe.configure({ timeout: 60_000 });

const t = (lang: 'sv' | 'en') => JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, `../src/content/i18n/${lang}.json`), 'utf8')) as Record<string, string>;

// A long how-to with code and asides: the update guide under docs/operate/. Without the docs move, the development guide is used.
const guide = exists('en/docs/operate/update/') && exists('sv/docs/operate/update/') ? 'docs/operate/update/' : 'docs/development/';
const reference = largest('en/docs/reference', 'en/docs/reference/mcp/');

const pages = [
  { name: 'language chooser', path: '' },
  { name: 'home sv', path: 'sv/' },
  { name: 'home en', path: 'en/' },
  { name: 'pricing', path: 'sv/pricing/' },
  { name: 'buy', path: 'sv/buy/' },
  { name: '404', path: 'sv/does-not-exist/' },
  { name: 'guide', path: `en/${guide}` },
  { name: 'english fallback under /sv/', path: 'sv/docs/explanation/architecture/backend/' },
  { name: 'largest reference', path: reference },
];
const widths = [1280, 375];
const schemes = ['light', 'dark'] as const;
const axeTags = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'];

async function ready(page: Page) {
  await page.waitForLoadState('networkidle');
  // The search button is disabled until its script has run.
  await page.waitForFunction(() => {
    const button = document.querySelector<HTMLButtonElement>('button[data-open-modal]');
    return !button || !button.disabled;
  });
}

const violationsOf = async (page: Page) => {
  // landmark-unique is a best-practice rule outside the WCAG tags; it replaces html-validate's unique-landmark (see .htmlvalidate.md).
  const axe = await new AxeBuilder({ page }).withTags(axeTags).withRules(['landmark-unique']).analyze();
  // Expressive Code marks scrollable code blocks role=region without a name; that is upstream markup, so code blocks are left out of landmark-unique.
  return axe.violations
    .map((v) => ({ ...v, nodes: v.id === 'landmark-unique' ? v.nodes.filter((n) => !n.target.join(' ').includes('pre')) : v.nodes }))
    .filter((v) => v.nodes.length > 0)
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`);
};

for (const p of pages) {
  for (const width of widths) {
    for (const scheme of schemes) {
      test.describe(`${p.name} @${width} ${scheme}`, () => {
        test.beforeEach(async ({ page }) => {
          await page.setViewportSize({ width, height: width > 600 ? 900 : 812 });
          await page.emulateMedia({ colorScheme: scheme });
          await page.goto(base + p.path);
          await ready(page);
        });
        test('axe: no wcag2a/aa, 2.1 AA or 2.2 AA violations', async ({ page }) => {
          expect(await violationsOf(page)).toEqual([]);
        });
        test('hit areas are at least 44 px outside running text', async ({ page }) => {
          expect(await smallTargets(page)).toEqual([]);
        });
      });
    }
  }
}

// The hit area of a lone link must not depend on the font: CI's fallback font has a smaller line box than the local one.
for (const p of pages.filter((q) => ['home sv', 'home en', 'pricing', 'buy'].includes(q.name))) {
  for (const width of widths) {
    test(`${p.name} @${width}: hit areas stay 44 px with a different fallback font`, async ({ page }) => {
      await page.setViewportSize({ width, height: width > 600 ? 900 : 812 });
      await page.goto(base + p.path);
      await ready(page);
      // A constructed stylesheet is not an inline style, so the page's CSP lets it through.
      await page.evaluate(() => {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync('* { font-family: "DejaVu Sans", sans-serif !important; }');
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      });
      expect(await smallTargets(page)).toEqual([]);
    });
  }
}

// Privacy, CSP and byte budget do not depend on the colour scheme, so one load per page and width is enough.
for (const p of pages) {
  for (const width of widths) {
    test.describe(`${p.name} @${width} network`, () => {
      let net: ReturnType<typeof trackNetwork>;
      let csp: () => Promise<string[]>;
      test.beforeEach(async ({ page }) => {
        await page.setViewportSize({ width, height: width > 600 ? 900 : 812 });
        net = trackNetwork(page, origin);
        csp = await trackCspViolations(page);
        await page.goto(base + p.path);
        await ready(page);
        await net.settle();
      });
      test('no requests to other origins, no CSP violations', async () => {
        expect(net.external, 'requests to other origins').toEqual([]);
        expect(await csp(), 'securitypolicyviolation events').toEqual([]);
      });
      test('no cookies, localStorage only holds the theme', async ({ page, context }) => {
        expect(await page.evaluate(() => document.cookie), 'document.cookie').toBe('');
        expect(await context.cookies(), 'cookies').toEqual([]);
        const keys = await page.evaluate(() => Object.keys(localStorage));
        expect(keys.filter((k) => k !== 'starlight-theme'), 'localStorage keys').toEqual([]);
      });
      test('byte budget (gzip) per type', async () => {
        expect(net.bytes.script ?? 0, 'JS without the search').toBeLessThanOrEqual(budget.scriptGzip);
        expect(net.bytes.stylesheet ?? 0, 'CSS').toBeLessThanOrEqual(budget.styleGzip);
        expect(net.bytes.font ?? 0, 'fonts').toBe(0);
        const weight = Object.entries(net.bytes).filter(([type]) => type !== 'image').reduce((sum, [, n]) => sum + n, 0);
        expect(weight + net.searchBytes, 'page weight without images, with the search code').toBeLessThanOrEqual(budget.pageGzip);
      });
    });
  }
}

for (const p of pages) {
  for (const width of [320, 375, 412]) {
    test(`${p.name} @${width}: no horizontal scroll`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(base + p.path);
      await page.waitForLoadState('networkidle');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `scrollWidth - clientWidth on ${p.path}`).toBeLessThanOrEqual(0);
    });
  }
}

// Search dialog and mobile menu open: axe and target sizes again, because both are overlays with their own markup.
for (const width of widths) {
  for (const scheme of schemes) {
    test(`search dialog open @${width} ${scheme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width > 600 ? 900 : 812 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(`${base}en/${guide}`);
      await ready(page);
      await page.locator('button[data-open-modal]').click();
      await expect(page.locator('dialog[open]')).toBeVisible();
      await page.locator('dialog input').fill('journal');
      await expect(page.locator('dialog a').first()).toBeVisible();
      expect(await violationsOf(page)).toEqual([]);
      // The result list is Pagefind's; its links are rows spanning the dialog, so they must be at least 44 px high.
      const rows = await page.locator('dialog .pagefind-ui__result-link').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
      expect(rows.filter((h) => h < 44 - 0.5), 'search result rows under 44 px').toEqual([]);
    });
  }
}

test.describe('mobile menu open', () => {
  for (const scheme of schemes) {
    test(`docs page (Starlight menu button) ${scheme}`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(`${base}en/${guide}`);
      await ready(page);
      await page.locator('button.sl-menu-button').click();
      await expect(page.locator('#starlight__sidebar')).toBeVisible();
      expect(await violationsOf(page)).toEqual([]);
      expect(await smallTargets(page), 'targets smaller than 44 px').toEqual([]);
    });

    test(`marketing page (details menu) ${scheme}`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(`${base}sv/pricing/`);
      await ready(page);
      await page.locator('.site-menu summary').click();
      await expect(page.locator('.site-menu__panel')).toBeVisible();
      expect(await violationsOf(page)).toEqual([]);
      expect(await smallTargets(page), 'targets smaller than 44 px').toEqual([]);
    });
  }
});

test('reduced motion: no transitions or animations', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const p of ['sv/', `en/${guide}`]) {
    await page.goto(base + p);
    await page.waitForLoadState('networkidle');
    const moving = await page.evaluate(() => {
      const bad: string[] = [];
      document.querySelectorAll('body *').forEach((el) => {
        const s = getComputedStyle(el);
        const dur = (v: string) => v.split(',').some((d) => parseFloat(d) > 0);
        if (dur(s.transitionDuration) || dur(s.animationDuration)) bad.push(`${el.tagName.toLowerCase()}.${String(el.className).split(/\s+/)[0]}`);
      });
      return bad;
    });
    expect(moving, `elements with motion on ${p}`).toEqual([]);
  }
});

test.describe('keyboard order in the header', () => {
  async function order(page: Page, steps: number) {
    const found: string[] = [];
    for (let i = 0; i < steps; i++) {
      await page.keyboard.press('Tab');
      found.push(
        await page.evaluate(() => {
          const e = document.activeElement as HTMLElement;
          if (e.matches('.sl-skip-link')) return 'skip';
          if (e.matches('.wordmark')) return 'brand';
          if (e.closest('.site-nav')) return 'nav';
          if (e.matches('button[data-open-modal]')) return 'search';
          if (e.closest('starlight-theme-select')) return 'theme';
          if (e.closest('starlight-lang-select')) return 'language';
          if (e.matches('.sl-menu-button')) return 'menu';
          return 'other';
        }),
      );
    }
    return found;
  }
  const firstOf = (seq: string[]) => seq.filter((v, i) => v !== 'other' && seq.indexOf(v) === i);

  test('desktop: skip link, brand, navigation, search, theme, language', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${base}en/${guide}`);
    await ready(page);
    expect(firstOf(await order(page, 9))).toEqual(['skip', 'brand', 'nav', 'search', 'theme', 'language']);
  });

  test('mobile: skip link, brand, search, menu', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${base}en/${guide}`);
    await ready(page);
    const seq = firstOf(await order(page, 6));
    expect(seq.slice(0, 3)).toEqual(['skip', 'brand', 'search']);
    expect(seq).toContain('menu');
    expect(seq.indexOf('menu')).toBeGreaterThan(seq.indexOf('search'));
  });
});

test.describe('search', () => {
  test('Ctrl+K opens the dialog, "dagbok" hits Swedish pages', async ({ page }) => {
    await page.goto(`${base}sv/`);
    await ready(page);
    await page.keyboard.press('Control+k');
    await expect(page.locator('dialog[open]')).toBeVisible();
    await page.locator('dialog input').fill('dagbok');
    const links = page.locator('dialog .pagefind-ui__result-link');
    await expect(links.first()).toBeVisible();
    const hrefs = await links.evaluateAll((els) => els.map((e) => e.getAttribute('href') ?? ''));
    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.filter((h) => !h.startsWith(`${base}sv/`)), 'Swedish search returns only Swedish pages').toEqual([]);
  });

  test('Ctrl+K opens the dialog, "journal" hits English pages', async ({ page }) => {
    await page.goto(`${base}en/`);
    await ready(page);
    await page.keyboard.press('Control+k');
    await expect(page.locator('dialog[open]')).toBeVisible();
    await page.locator('dialog input').fill('journal');
    const links = page.locator('dialog .pagefind-ui__result-link');
    await expect(links.first()).toBeVisible();
    const hrefs = await links.evaluateAll((els) => els.map((e) => e.getAttribute('href') ?? ''));
    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.filter((h) => !h.startsWith(`${base}en/`)), 'English search returns only English pages').toEqual([]);
  });

  // The "/" shortcut from the design sits next to Ctrl+K. Starlight's search only listens for Ctrl/Cmd+K, so the Search
  // override (website/src/components/overrides/Search.astro) adds "/".
  test('"/" opens the dialog', async ({ page }) => {
    await page.goto(`${base}sv/`);
    await ready(page);
    await page.locator('body').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('/');
    await expect(page.locator('dialog[open]')).toBeVisible();
  });
});

test('the language selector on a guide leads to the same page in English', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${base}sv/${guide}`);
  await ready(page);
  await page.locator('starlight-lang-select select:visible').selectOption({ label: 'English' });
  await page.waitForURL(`**/en/${guide}`);
  expect(new URL(page.url()).pathname).toBe(`${base}en/${guide}`);
});

test.describe('fallback banner', () => {
  test('an English page under /sv/ says it is English only', async ({ page }) => {
    await page.goto(`${base}sv/docs/explanation/architecture/backend/`);
    await expect(page.locator('main').getByText(t('sv')['i18n.untranslatedContent'])).toBeVisible();
  });
  test('a translated page under /sv/ shows no banner', async ({ page }) => {
    await page.goto(`${base}sv/pricing/`);
    await expect(page.locator('main').getByText(t('sv')['i18n.untranslatedContent'])).toHaveCount(0);
  });
});

// Negative tests: each control must fail on bad input. They serve a small page from a fixture route on the same origin.
test.describe('the checks fail on bad pages', () => {
  const fixture = (body: string, head = '') =>
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>x</title>${head}</head><body>${body}</body></html>`;
  const serve = async (page: Page, html: string) => {
    await page.route('**/__fixture__/', (route) => route.fulfill({ contentType: 'text/html', body: html }));
    await page.route('https://tracker.example/**', (route) => route.abort());
    await page.goto(`${origin}/__fixture__/`);
  };

  test('a 30 px button is reported', async ({ page }) => {
    await serve(page, fixture('<button style="width:30px;height:30px">x</button>'));
    expect(await smallTargets(page)).toEqual([expect.stringContaining('30x30')]);
  });

  test('a 44 px button and an inline link in a sentence pass', async ({ page }) => {
    await serve(page, fixture('<button style="width:44px;height:44px">x</button><p>Read <a href="/a/">this</a> now.</p>'));
    expect(await smallTargets(page)).toEqual([]);
  });

  test('an external script is reported as an external request and as a CSP violation', async ({ page }) => {
    const net = trackNetwork(page, origin);
    const csp = await trackCspViolations(page);
    const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'">`;
    await page.route('**/__fixture__/', (route) =>
      route.fulfill({ contentType: 'text/html', body: fixture('<script src="https://tracker.example/t.js"></script>', policy) }),
    );
    await page.route('https://tracker.example/**', (route) => route.abort());
    await page.goto(`${origin}/__fixture__/`);
    expect(net.external).toEqual(['https://tracker.example/t.js']);
    expect((await csp()).join('\n')).toContain('script-src');
  });

  test('a cookie and a stray localStorage key are visible to the privacy check', async ({ page, context }) => {
    await serve(page, fixture('<script>document.cookie="a=1";localStorage.setItem("id","1")</script>'));
    expect(await page.evaluate(() => document.cookie)).toBe('a=1');
    expect((await context.cookies()).length).toBe(1);
    expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(['id']);
  });

  test('axe finds a button without a name', async ({ page }) => {
    await serve(page, fixture('<main><h1>x</h1><button style="width:50px;height:50px"></button></main>'));
    const axe = await new AxeBuilder({ page }).withTags(axeTags).analyze();
    expect(axe.violations.map((v) => v.id)).toContain('button-name');
  });
});

test('language selector on /sv/docs/operate/ leads to /en/docs/operate/', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${base}sv/docs/operate/`);
  await ready(page);
  await page.locator('starlight-lang-select select:visible').selectOption({ label: 'English' });
  await page.waitForURL('**/en/docs/operate/');
});
