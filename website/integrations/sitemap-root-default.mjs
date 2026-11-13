// The sitemap integration inside Starlight lists the root page (the language chooser) as the English version of
// itself, so the root and /en/ both claim hreflang="en". The root is the fallback for readers whose language
// matches neither version, which is what hreflang="x-default" says.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function rootAsDefault(xml, home) {
  return xml.split(`hreflang="en" href="${home}"`).join(`hreflang="x-default" href="${home}"`);
}

/** `home` is the absolute URL of the site root, with the base path. */
export default function sitemapRootDefault(home) {
  return {
    name: 'sitemap-root-default',
    hooks: {
      'astro:build:done': ({ dir }) => {
        const root = fileURLToPath(dir);
        for (const name of fs.readdirSync(root).filter((f) => /^sitemap-\d+\.xml$/.test(f))) {
          const file = path.join(root, name);
          const xml = fs.readFileSync(file, 'utf8');
          const next = rootAsDefault(xml, home);
          if (next !== xml) fs.writeFileSync(file, next);
        }
      },
    },
  };
}
