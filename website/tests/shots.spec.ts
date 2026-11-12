import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Screenshots and layout measurements for the main page types. Screenshots go to SHOTS_DIR
// (default test-results/shots) for visual review. The base path comes from SITE_BASE (default: domain root).
const shotsDir = process.env.SHOTS_DIR ?? 'test-results/shots';
const base = ((process.env.SITE_BASE ?? '').replace(/\/+$/, '') + '/').replace(/^\/\/$/, '/');

const pages = [
  { name: 'home', path: 'sv/' },
  { name: 'pricing', path: 'sv/pricing/' },
  { name: 'buy', path: 'sv/buy/' },
  { name: 'docs', path: 'en/docs/start/self-hosted-server/' },
  { name: 'docs-sv-fallback', path: 'sv/docs/explanation/architecture/backend/' },
];
const viewports = [
  { w: 1280, h: 900 },
  { w: 412, h: 860 },
  { w: 375, h: 812 },
  { w: 320, h: 700 },
];

async function measure(page: Page) {
  return page.evaluate(() => {
    const rect = (el: Element) => el.getBoundingClientRect();
    const visible = (el: Element) => {
      const r = rect(el);
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    const doc = document.documentElement;
    const small: string[] = [];
    // Targets outside running text must be at least 44 x 44 (48 for buttons). Inline links in prose are exempt.
    document.querySelectorAll('.btn:not([aria-disabled]), .site-header button, .site-header [data-open-modal], .site-header summary, .site-header__prefs a, .copy button, .sl-menu-button').forEach((el) => {
      if (!visible(el)) return;
      const r = rect(el);
      // The search field is 40 px high with a ::after that extends the hit area by 4 px on every side.
      const min = el.matches('.copy button') ? 44 : el.matches('[data-open-modal]') ? 40 : 48;
      if (r.height < min - 0.5 || r.width < min - 0.5) small.push(`${el.className || el.tagName} ${Math.round(r.width)}x${Math.round(r.height)}`);
    });
    return { overflow: doc.scrollWidth - doc.clientWidth, small, title: document.title };
  });
}

for (const p of pages) {
  for (const vp of viewports) {
    for (const scheme of ['light', 'dark'] as const) {
      test(`${p.name} ${vp.w} ${scheme}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.w, height: vp.h });
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' });
        const violations: string[] = [];
        page.on('console', (m) => m.type() === 'error' && violations.push(m.text()));
        await page.goto(base + p.path);
        await page.waitForLoadState('networkidle');
        fs.mkdirSync(shotsDir, { recursive: true });
        // The header's backdrop blur can make full-page capture fail in headless Chromium; fall back to the viewport.
        const file = path.join(shotsDir, `${p.name}-${scheme}-${vp.w}.png`);
        await page.screenshot({ path: file, fullPage: true }).catch(() => page.screenshot({ path: file }));
        if (p.name.startsWith('docs')) await page.screenshot({ path: file.replace('.png', '-top.png') });
        const m = await measure(page);
        expect(m.overflow, `horizontal overflow on ${p.path} at ${vp.w}`).toBeLessThanOrEqual(0);
        expect(m.small, `targets too small on ${p.path}`).toEqual([]);
        expect(violations).toEqual([]);
      });
    }
  }
}
