import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { run, diagramHash, truncateWords } from './sync-docs.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, 'fixtures/basic');
const map = await import(pathToFileURL(path.join(here, 'fixtures/map.mjs')).href);
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'sync-test-'));
const REPO = 'https://github.com/CarlOMattsson/roadlake-sidekick';

function sync(opts = {}) {
  const outDir = tmp();
  const result = run({ map, sourceRoot: FIXTURE, outDir, diagramsDir: path.join(outDir, 'diagrams'), base: '/base', ...opts });
  const read = (locale, slug) => fs.readFileSync(path.join(outDir, 'src/content/docs', locale, `${slug}.md`), 'utf8');
  const exists = (locale, slug) => fs.existsSync(path.join(outDir, 'src/content/docs', locale, `${slug}.md`));
  return { outDir, result, read, exists };
}

function writeTree(files) {
  const root = tmp();
  for (const [rel, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), text);
  }
  return root;
}

test('maps X.md to en and X.sv.md to sv, README to the folder index', () => {
  const { exists, result } = sync();
  assert.deepEqual(result.errors, []);
  assert.ok(exists('en', 'docs/guide/a') && exists('sv', 'docs/guide/a'));
  assert.ok(exists('en', 'docs/index') && exists('sv', 'docs/index'));
});

test('title, explicit description, and the language row is removed', () => {
  const { read } = sync();
  const a = read('en', 'docs/guide/a');
  assert.match(a, /^title: "Page A"$/m);
  assert.match(a, /^description: "Custom description for A\."$/m);
  assert.doesNotMatch(a, /\[Svenska\]\(/);
  assert.doesNotMatch(a, /^# Page A/m);
  assert.doesNotMatch(a, /description:.*-->/);
  const home = read('en', 'docs/index');
  assert.doesNotMatch(home, /\[Svenska\]/);
});

test('description falls back to the first paragraph, cut at a word end', () => {
  const { read } = sync();
  assert.match(read('en', 'docs/index'), /^description: "First paragraph of the home page, with a link in it\."$/m);
  const long = Array.from({ length: 80 }, (_, i) => `word${i}`).join(' ');
  const cut = truncateWords(long, 160);
  assert.ok(cut.length <= 160 && cut.endsWith('…'));
  assert.ok(long.startsWith(cut.slice(0, -1)) && long[cut.length - 1] === ' ');
});

test('page links are relative, keep anchors, and prefer the .sv.md twin from Swedish pages', () => {
  const { read } = sync();
  const en = read('en', 'docs/guide/a');
  assert.match(en, /\[B\]\(\.\.\/b\/#section\)/);
  assert.match(en, /\[home\]\(\.\.\/\.\.\/\)/);
  assert.match(en, /\[self anchor\]\(#local\)/);
  assert.match(en, /<a href="\.\.\/b\/">b html<\/a>/);
  const sv = read('sv', 'docs/guide/a');
  assert.match(sv, /\[B\]\(\.\.\/b\/#section\)/);
  assert.match(sv, /\[en-only\]\(\.\.\/\.\.\/en-only\/\)/);
});

test('files that are not pages go to GitHub blob, folders to tree, externals are untouched', () => {
  const { read } = sync();
  const en = read('en', 'docs/guide/a');
  assert.ok(en.includes(`[compose](${REPO}/blob/main/deploy/compose.yaml)`));
  assert.ok(en.includes(`[dir](${REPO}/tree/main/backend/src)`));
  assert.ok(en.includes('[external](https://example.com/x)'));
  assert.doesNotMatch(en, /target=/);
});

test('links inside code blocks and inline code are not changed', () => {
  const { read } = sync();
  const en = read('en', 'docs/guide/a');
  assert.ok(en.includes('see [not a link](b.md)'));
  assert.ok(en.includes('`[code](b.md)`'));
});

test('images are copied and linked under the base path', () => {
  const { read, outDir } = sync();
  const en = read('en', 'docs/guide/a');
  assert.ok(en.includes('![Pic alt](/base/docs-images/pic.png)'));
  assert.ok(en.includes('<img src="/base/docs-images/pic.png" alt="x">'));
  assert.ok(fs.existsSync(path.join(outDir, 'public/docs-images/pic.png')));
});

test('a missing alt text fails the sync and writes nothing', () => {
  const root = writeTree({ 'docs/p.md': '# P\n\n![](x.png)\n', 'docs/x.png': 'x' });
  const outDir = tmp();
  const result = run({ map: { include: ['docs/'] }, sourceRoot: root, outDir, base: '' });
  assert.equal(result.errors.length, 1);
  assert.match(result.errors[0], /image without alt text/);
  assert.equal(fs.existsSync(path.join(outDir, 'src')), false);
});

test('overlay wins over the root file', () => {
  const { read } = sync();
  assert.match(read('en', 'docs/guide/b'), /Overlay B text wins/);
  assert.match(read('sv', 'docs/guide/b'), /Svensk B/);
});

test('an English page without a Swedish twin exists only under en/', () => {
  const { exists } = sync();
  assert.ok(exists('en', 'docs/en-only'));
  assert.equal(exists('sv', 'docs/en-only'), false);
});

test('root files become pages, and the order list sets sidebar order', () => {
  const { exists, read } = sync();
  assert.ok(exists('en', 'docs/security-policy') && exists('sv', 'docs/security-policy'));
  assert.match(read('en', 'docs/guide/b'), /sidebar:\n {2}order: 1\n/);
  assert.match(read('en', 'docs/guide/a'), /sidebar:\n {2}order: 2\n/);
  assert.doesNotMatch(read('en', 'docs/en-only'), /order:/);
  assert.match(read('en', 'docs/guide/a'), /^lastUpdated: false$/m);
});

test('a title from the map replaces the heading of the source, and only in the locale it names', () => {
  const { read } = sync();
  assert.match(read('en', 'docs/guide/b'), /^title: "Title from the map"$/m);
  assert.doesNotMatch(read('sv', 'docs/guide/b'), /Title from the map/);
  const bad = run({ map: { ...map, titles: { 'docs/ghost': { en: 'X' } } }, sourceRoot: FIXTURE, outDir: tmp(), verifyOnly: true });
  assert.deepEqual(bad.errors, ['Missing source in content-map.mjs: titles: docs/ghost']);
});

const MERMAID = (extra = '') => `flowchart LR\n  accTitle: Flow\n  accDescr: A goes to B.${extra}\n  A --> B\n`;

test('a mermaid block with rendered SVGs becomes a figure', () => {
  const root = writeTree({ 'docs/m.md': `# M\n\nText.\n\n\`\`\`mermaid\n${MERMAID()}\`\`\`\n` });
  const outDir = tmp();
  const diagramsDir = path.join(outDir, 'diagrams');
  fs.mkdirSync(diagramsDir);
  const hash = diagramHash(MERMAID());
  for (const m of ['light', 'dark']) fs.writeFileSync(path.join(diagramsDir, `${hash}.${m}.svg`), '<svg/>');
  const result = run({ map: { include: ['docs/'] }, sourceRoot: root, outDir, diagramsDir, base: '/b' });
  assert.deepEqual(result.errors, []);
  const page = fs.readFileSync(path.join(outDir, 'src/content/docs/en/docs/m.md'), 'utf8');
  assert.ok(page.includes(`/b/docs-images/diagrams/${hash}.light.svg`) && page.includes('alt="Flow"') && page.includes('<figcaption>A goes to B.</figcaption>'));
  assert.ok(fs.existsSync(path.join(outDir, `public/docs-images/diagrams/${hash}.dark.svg`)));
});

test('a mermaid block without rendered SVGs names the command that fixes it', () => {
  const root = writeTree({ 'docs/m.md': `# M\n\n\`\`\`mermaid\n${MERMAID()}\`\`\`\n` });
  const result = run({ map: { include: ['docs/'] }, sourceRoot: root, outDir: tmp(), diagramsDir: path.join(tmp(), 'none'), base: '' });
  assert.match(result.errors[0], /npm --prefix website\/tools\/diagrams run render/);
});

test('a mermaid block without accTitle/accDescr is an error', () => {
  const root = writeTree({ 'docs/m.md': '# M\n\n```mermaid\nflowchart LR\n  A --> B\n```\n' });
  const result = run({ map: { include: ['docs/'] }, sourceRoot: root, outDir: tmp(), base: '' });
  assert.match(result.errors[0], /accTitle/);
});

test('--verify-sources writes nothing and fails when a source is missing', () => {
  const outDir = tmp();
  const ok = run({ map, sourceRoot: FIXTURE, outDir, verifyOnly: true });
  assert.deepEqual(ok.errors, []);
  assert.equal(fs.readdirSync(outDir).length, 0);
  const bad = run({ map: { ...map, rootFiles: [{ src: 'NOPE', slug: 'docs/nope' }], order: { 'docs/guide': ['ghost'] } }, sourceRoot: FIXTURE, outDir, verifyOnly: true });
  assert.equal(bad.errors.length, 2);
});

test('CLI: --verify-sources exits 1 for a missing source and 0 otherwise', () => {
  const script = path.join(here, 'sync-docs.mjs');
  const badMap = path.join(tmp(), 'bad-map.mjs');
  fs.writeFileSync(badMap, "export const include = ['docs/missing/'];\n");
  const good = spawnSync('node', [script, '--verify-sources', '--source-root', FIXTURE, '--map', path.join(here, 'fixtures/map.mjs')]);
  assert.equal(good.status, 0, good.stderr.toString());
  const bad = spawnSync('node', [script, '--verify-sources', '--source-root', FIXTURE, '--map', badMap]);
  assert.equal(bad.status, 1);
  assert.match(bad.stderr.toString(), /docs\/missing\//);
});

test('the repository content map points only at existing sources', () => {
  const repo = path.resolve(here, '..', '..');
  const out = spawnSync('node', [path.join(here, 'sync-docs.mjs'), '--verify-sources', '--source-root', repo]);
  assert.equal(out.status, 0, out.stderr.toString());
});

test('assets listed in the content map are copied even when no page references them', () => {
  const root = writeTree({ 'docs/p.md': '# P\n\nText.\n', 'docs/images/rooms/a.png': 'x' });
  const outDir = tmp();
  const result = run({ map: { include: ['docs/'], exclude: ['docs/images/'], assets: ['docs/images/rooms/'] }, sourceRoot: root, outDir, base: '' });
  assert.deepEqual(result.errors, []);
  assert.ok(fs.existsSync(path.join(outDir, 'public/docs-images/rooms/a.png')));
});

test('prose placeholders such as <your server> are escaped, real HTML and autolinks are not', async () => {
  const { escapeProsePlaceholders: esc } = await import('./sync-docs.mjs');
  assert.equal(esc('Connect to <your server>?'), 'Connect to &lt;your server>?');
  assert.equal(esc('<din-domän>'), '&lt;din-domän>');
  assert.equal(esc('<kbd>Ctrl</kbd> <br/> <a href="x">y</a> <https://a.b/c> <me@x.se> <!-- c -->'), '<kbd>Ctrl</kbd> <br/> <a href="x">y</a> <https://a.b/c> <me@x.se> <!-- c -->');
});
