import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { addInlineHashes } from '../integrations/csp-inline-hashes.mjs';

const h = (t) => `'sha256-${crypto.createHash('sha256').update(t).digest('base64')}'`;
const page = (body) =>
  `<html><head><meta http-equiv="content-security-policy" content="default-src 'self'; script-src 'self' 'sha256-known'; style-src 'self'"></head><body>${body}</body></html>`;

test('adds hashes for inline scripts and styles, and only the attribute form of inline styles', () => {
  const out = addInlineHashes(page('<script>var a=1;</script><style>b{color:red}</style>'));
  assert.ok(out.includes(`script-src 'self' 'sha256-known' ${h('var a=1;')}`));
  assert.ok(out.includes(`style-src 'self' ${h('b{color:red}')}`));
  assert.ok(out.includes("style-src-attr 'unsafe-inline'"));
  assert.doesNotMatch(out, /script-src[^;]*unsafe-inline/);
});

test('leaves external scripts and JSON data blocks alone', () => {
  const out = addInlineHashes(page('<script src="/a.js"></script><script type="application/json">{}</script>'));
  assert.ok(!out.includes(h('{}')));
});

test('pages without a CSP meta tag are returned unchanged', () => {
  const html = '<html><body><script>x()</script></body></html>';
  assert.equal(addInlineHashes(html), html);
});

import { headDefaultsToRoot, rootAsDefault } from '../integrations/root-as-default.mjs';

test('sitemap: the site root becomes x-default, the language pages keep their language', () => {
  const xml = '<xhtml:link hreflang="en" href="https://x.test/"/><xhtml:link hreflang="en" href="https://x.test/en/"/><xhtml:link hreflang="sv" href="https://x.test/sv/"/>';
  assert.equal(
    rootAsDefault(xml, 'https://x.test/'),
    '<xhtml:link hreflang="x-default" href="https://x.test/"/><xhtml:link hreflang="en" href="https://x.test/en/"/><xhtml:link hreflang="sv" href="https://x.test/sv/"/>',
  );
});

test('page head: the x-default alternate of a language home page points at the site root', () => {
  const head = '<link rel="alternate" hreflang="en" href="https://x.test/en/"/><link rel="alternate" hreflang="x-default" href="https://x.test/en/"/>';
  assert.equal(
    headDefaultsToRoot(head, 'https://x.test/'),
    '<link rel="alternate" hreflang="en" href="https://x.test/en/"/><link rel="alternate" hreflang="x-default" href="https://x.test/"/>',
  );
});
