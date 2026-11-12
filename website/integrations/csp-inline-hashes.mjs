// Astro hashes the inline scripts and styles it emits itself, but not the `is:inline` scripts and <style> blocks that
// Starlight's components write (theme provider, search button, sidebar state). Their content is static, so this
// build step hashes every remaining inline <script> and <style> in dist/ and adds the hashes to the page's CSP
// meta tag. No 'unsafe-inline' for scripts or style elements. Style *attributes* (Starlight's selects and search
// button, Expressive Code) cannot be covered by hashes, so only `style-src-attr 'unsafe-inline'` is added.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const hash = (text) => `'sha256-${crypto.createHash('sha256').update(text).digest('base64')}'`;

function* htmlFiles(dir) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) yield* htmlFiles(full);
    else if (ent.name.endsWith('.html')) yield full;
  }
}

export function addInlineHashes(html) {
  const meta = html.match(/<meta http-equiv="content-security-policy" content="([^"]*)"\s*\/?>/i);
  if (!meta) return html;
  let policy = meta[1];
  const add = (directive, hashes) => {
    const re = new RegExp(`(${directive} [^;]*)`);
    const missing = [...new Set(hashes)].filter((h) => !policy.includes(h));
    if (!missing.length) return;
    policy = re.test(policy) ? policy.replace(re, `$1 ${missing.join(' ')}`) : `${policy}; ${directive} 'self' ${missing.join(' ')}`;
  };
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)([^>]*)>([\s\S]*?)<\/script>/gi)]
    .filter((m) => !/type="(application\/(ld\+)?json|importmap)"/i.test(m[1]) && m[2].trim())
    .map((m) => hash(m[2]));
  const styles = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].filter((m) => m[1].trim()).map((m) => hash(m[1]));
  add('script-src', scripts);
  add('style-src', styles);
  if (!/style-src-attr/.test(policy)) policy = `${policy.replace(/;?\s*$/, '')}; style-src-attr 'unsafe-inline'`;
  return html.replace(meta[0], meta[0].replace(meta[1], policy));
}

export default function cspInlineHashes() {
  return {
    name: 'csp-inline-hashes',
    hooks: {
      'astro:build:done': ({ dir }) => {
        for (const file of htmlFiles(fileURLToPath(dir))) {
          const html = fs.readFileSync(file, 'utf8');
          const next = addInlineHashes(html);
          if (next !== html) fs.writeFileSync(file, next);
        }
      },
    },
  };
}
