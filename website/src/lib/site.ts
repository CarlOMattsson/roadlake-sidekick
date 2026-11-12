import { getCollection } from 'astro:content';
import fs from 'node:fs';
import path from 'node:path';

// Build scripts run from website/ (npm --prefix website ...), so paths are resolved from the working directory.
const websiteDir = process.cwd();

export const REPO_URL = 'https://github.com/CarlOMattsson/roadlake-sidekick';
export const locales = ['sv', 'en'] as const;
export type Locale = (typeof locales)[number];

/** BASE_URL without a trailing slash ('' when the site is served from the domain root). */
export const base = import.meta.env.BASE_URL.replace(/\/$/, '');

/** The product version, read at build time from the same file as tools/check-version-sync.py. */
export function productVersion(): string {
  try {
    return JSON.parse(fs.readFileSync(path.resolve(websiteDir, '..', 'frontend/package.json'), 'utf8')).version ?? 'unknown';
  } catch {
    return 'unknown';
  }
}

let ids: Set<string> | undefined;
async function docIds(): Promise<Set<string>> {
  ids ??= new Set((await getCollection('docs')).map((e) => e.id));
  return ids;
}

/**
 * Link to a page by its locale-free path ('docs/start', 'pricing'). Returns undefined when the page does
 * not exist yet (neither in the locale nor as the English fallback), so navigation never shows a dead link.
 */
export async function pageHref(locale: Locale, path: string | string[]): Promise<string | undefined> {
  const all = await docIds();
  const has = (l: string, p: string) => all.has(`${l}/${p}`) || all.has(`${l}/${p}/index`);
  for (const p of Array.isArray(path) ? path : [path]) {
    if (has(locale, p) || has('en', p)) return `${base}/${locale}/${p}/`;
  }
  return undefined;
}

/** Pixel size of a PNG in public/docs-images (read from the header at build time). */
export function pngSize(publicPath: string): { width: number; height: number } {
  const buf = fs.readFileSync(path.resolve(websiteDir, 'public', publicPath));
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

export function localeOf(pathname: string): Locale {
  const rest = pathname.slice(base.length).split('/')[1];
  return rest === 'sv' ? 'sv' : 'en';
}

/** Report-a-problem link: opens a new GitHub issue prefilled with the page address. */
export function reportUrl(pageUrl: string, title: string, label: string): string {
  const q = new URLSearchParams({ title: `${label}: ${title}`, body: `Page: ${pageUrl}\n\n` });
  return `${REPO_URL}/issues/new?${q.toString()}`;
}
