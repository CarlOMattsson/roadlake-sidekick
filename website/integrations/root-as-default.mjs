// The site root is the language chooser, so it is the fallback for readers whose language matches neither
// version, which is what hreflang="x-default" says. Starlight does not know that:
// - its sitemap lists the root as the English version of itself, so the root and /en/ both claim hreflang="en";
// - its page head points x-default at the English page, which disagrees with the sitemap on the two home pages.
// This integration makes both say the same thing.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const LANGUAGE_HOMES = ['sv', 'en'];

export function rootAsDefault(xml, home) {
  return xml.split(`hreflang="en" href="${home}"`).join(`hreflang="x-default" href="${home}"`);
}

/** Points the x-default alternate in a page head at the site root. */
export function headDefaultsToRoot(html, home) {
  return html.replace(/(<link rel="alternate" hreflang="x-default" href=")[^"]*(")/, `$1${home}$2`);
}

function rewrite(file, transform) {
  const before = fs.readFileSync(file, 'utf8');
  const after = transform(before);
  if (after !== before) fs.writeFileSync(file, after);
}

/** `home` is the absolute URL of the site root, with the base path. */
export default function rootAsDefaultIntegration(home) {
  return {
    name: 'root-as-default',
    hooks: {
      'astro:build:done': ({ dir }) => {
        const root = fileURLToPath(dir);
        for (const name of fs.readdirSync(root).filter((f) => /^sitemap-\d+\.xml$/.test(f))) {
          rewrite(path.join(root, name), (xml) => rootAsDefault(xml, home));
        }
        for (const locale of LANGUAGE_HOMES) {
          rewrite(path.join(root, locale, 'index.html'), (html) => headDefaultsToRoot(html, home));
        }
      },
    },
  };
}
