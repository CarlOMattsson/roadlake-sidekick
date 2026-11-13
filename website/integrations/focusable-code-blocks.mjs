// A code block that scrolls sideways must be reachable with the keyboard, or its overflow is unreadable without a
// mouse. Expressive Code renders the <pre> without a tab stop, so this build step gives every code block one, with
// a region role and a label in the page language.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const LABELS = { sv: 'Kodblock', en: 'Code block' };

function* htmlFiles(dir) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) yield* htmlFiles(full);
    else if (ent.name.endsWith('.html')) yield full;
  }
}

export function makeCodeBlocksFocusable(html) {
  const lang = html.match(/<html[^>]*\blang="(\w+)"/i)?.[1] === 'sv' ? 'sv' : 'en';
  return html.replace(/<pre\b(?![^>]*\btabindex=)([^>]*\bdata-language=[^>]*)>/g, (_, attrs) => {
    const label = attrs.includes('aria-label=') ? '' : ` aria-label="${LABELS[lang]}"`;
    return `<pre${attrs} tabindex="0" role="region"${label}>`;
  });
}

export default function focusableCodeBlocks() {
  return {
    name: 'focusable-code-blocks',
    hooks: {
      'astro:build:done': ({ dir }) => {
        for (const file of htmlFiles(fileURLToPath(dir))) {
          const html = fs.readFileSync(file, 'utf8');
          const next = makeCodeBlocksFocusable(html);
          if (next !== html) fs.writeFileSync(file, next);
        }
      },
    },
  };
}
