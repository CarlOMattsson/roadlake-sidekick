import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import type { Page } from '@playwright/test';

// Shared by tests/site.spec.ts. The measurements are plain functions so the negative tests can run them on bad pages.

/** Base path from SITE_BASE (default: the domain root), with a trailing slash. */
export const base = ((process.env.SITE_BASE ?? '').replace(/\/+$/, '') + '/').replace(/^\/\/$/, '/');

export const distDir = path.resolve(import.meta.dirname, '..', 'dist');

/** Byte budgets (gzip, as GitHub Pages serves them). Search (Pagefind) is only fetched when the dialog opens. */
export const budget = {
  scriptGzip: 25 * 1024,
  styleGzip: 30 * 1024,
  pageGzip: 150 * 1024,
};

export type Network = {
  /** Requests to any origin other than the site itself. */
  external: string[];
  /** Gzipped body size per resource type, in bytes. The search code (Pagefind UI, loaded when idle) is counted separately. */
  bytes: Record<string, number>;
  searchBytes: number;
  /** Wait until all body reads have finished. */
  settle: () => Promise<void>;
};

/** Record every request (also blocked ones) and the gzip size of every response, per resource type. */
export function trackNetwork(page: Page, siteOrigin: string): Network {
  const net: Network = { external: [], bytes: {}, searchBytes: 0, settle: async () => {} };
  const pending: Promise<void>[] = [];
  page.on('request', (req) => {
    const url = req.url();
    if (url.startsWith('data:') || url.startsWith('blob:') || url.startsWith('about:')) return;
    if (new URL(url).origin !== siteOrigin) net.external.push(url);
  });
  page.on('response', (res) => {
    pending.push(
      res
        .body()
        .then((body) => {
          const type = res.request().resourceType();
          const size = zlib.gzipSync(body).length;
          // teknik.md 5.6: the JS budget is "without the search". Starlight loads the Pagefind UI when the page is idle.
          if (type === 'script' && /\/(ui-core|Search\.astro)[^/]*\.js$|\/pagefind\//.test(new URL(res.url()).pathname)) net.searchBytes += size;
          else net.bytes[type] = (net.bytes[type] ?? 0) + size;
        })
        .catch(() => {}),
    );
  });
  net.settle = async () => {
    await Promise.all(pending);
  };
  return net;
}

/** Collect `securitypolicyviolation` events. Call before the first navigation. */
export async function trackCspViolations(page: Page): Promise<() => Promise<string[]>> {
  await page.addInitScript(() => {
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener('securitypolicyviolation', (e) => {
      (window as unknown as { __csp: string[] }).__csp.push(`${e.violatedDirective} blocked ${e.blockedURI || 'inline'}`);
    });
  });
  return () => page.evaluate(() => (window as unknown as { __csp: string[] }).__csp ?? []);
}

/**
 * Visible links, buttons, summaries and form controls outside running text that are smaller than `min` px in either
 * direction. A control's hit area includes a `::after` that extends past its box (the search field does this).
 * Text links only need the height (their width is their words). Not measured: inline links inside a sentence, and elements
 * that are clipped (screen-reader-only), and the skip link until it has focus.
 */
export async function smallTargets(page: Page, min = 44): Promise<string[]> {
  return page.evaluate((limit) => {
    const out: string[] = [];
    const px = (v: string) => (v.endsWith('px') ? parseFloat(v) : NaN);
    document.querySelectorAll('a[href], button, summary, select, input:not([type=hidden]), [role=button]').forEach((el) => {
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none') return;
      if (!(el as HTMLElement).checkVisibility?.()) return;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 1 || rect.height <= 1) return; // clipped (sr-only)
      if (el.matches('.sl-skip-link') && document.activeElement !== el) return; // visible only on focus
      // Inline link: the element's parent has its own text around it.
      if (el.tagName === 'A' && el.parentElement) {
        const around = [...el.parentElement.childNodes].filter((n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? '').trim().length > 0);
        if (around.length > 0) return;
      }
      let w = rect.width;
      let h = rect.height;
      const after = getComputedStyle(el, '::after');
      if (after.content !== 'none' && after.position === 'absolute') {
        const [t, r, b, l] = [after.top, after.right, after.bottom, after.left].map(px);
        const inset = [t, r, b, l].map((v) => (Number.isFinite(v) && v < 0 ? -v : 0));
        h += inset[0] + inset[2];
        w += inset[1] + inset[3];
      }
      // A text link can only be as wide as its words, so for those only the height counts. Controls and icon links need both.
      const textLink = el.tagName === 'A' && (el.textContent ?? '').trim().length > 0 && el.querySelector('svg, img') === null;
      if ((!textLink && w < limit - 0.5) || h < limit - 0.5) {
        const name = (el.getAttribute('aria-label') ?? el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 30);
        out.push(`${el.tagName.toLowerCase()}${el.className ? '.' + String(el.className).split(/\s+/)[0] : ''} "${name}" ${Math.round(w)}x${Math.round(h)}`);
      }
    });
    return out;
  }, min);
}

/** Pages whose size we can read from dist/ without a browser. */
export function largest(dir: string, fallback: string): string {
  const root = path.join(distDir, dir);
  let best = { size: -1, rel: fallback };
  const walk = (d: string) => {
    for (const ent of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      const full = path.join(d, ent.name);
      if (ent.isDirectory()) walk(full);
      else if (ent.name === 'index.html') {
        const size = fs.statSync(full).size;
        if (size > best.size) best = { size, rel: path.relative(distDir, path.dirname(full)).split(path.sep).join('/') + '/' };
      }
    }
  };
  walk(root);
  return best.rel;
}

export const exists = (rel: string) => fs.existsSync(path.join(distDir, rel, 'index.html'));
