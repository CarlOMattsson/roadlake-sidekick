import test from 'node:test';
import assert from 'node:assert/strict';
import { makeCodeBlocksFocusable } from '../integrations/focusable-code-blocks.mjs';

test('gives a code block a tab stop, a region role and a label in the page language', () => {
  const sv = makeCodeBlocksFocusable('<html lang="sv"><pre data-language="bash"><code>x</code></pre></html>');
  assert.match(sv, /<pre data-language="bash" tabindex="0" role="region" aria-label="Kodblock">/);
  const en = makeCodeBlocksFocusable('<html lang="en"><pre data-language="json"></pre></html>');
  assert.match(en, /aria-label="Code block"/);
});

test('leaves plain pre elements and already focusable blocks alone', () => {
  const html = '<html lang="en"><pre>a</pre><pre data-language="js" tabindex="0"></pre></html>';
  assert.equal(makeCodeBlocksFocusable(html), html);
});
