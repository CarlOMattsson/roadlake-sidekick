// Negative tests for the post-build checks: each one must fail on a deliberately bad input (and pass on a good one).
// The inputs are written to a temp directory by the tests themselves. Needs python3; html-validate comes from node_modules.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const site = path.resolve(here, '..');
const repo = path.resolve(site, '..');
const python = (script, args, options = {}) =>
  spawnSync('python3', [path.join(here, script), ...args], { encoding: 'utf8', ...options });

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'site-checks-'));
const write = (root, rel, text) => {
  fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
  fs.writeFileSync(path.join(root, rel), text);
};
const page = (body, { hreflang = true } = {}) =>
  `<!doctype html><html lang="en"><head><title>t</title>${
    hreflang ? '<link rel="alternate" hreflang="sv" href="https://example.test/sv/"><link rel="alternate" hreflang="en" href="https://example.test/en/">' : ''
  }</head><body>${body}</body></html>`;

/** A tiny two-language site; `extra` is appended to the English page body. */
function dist(extra = '', options) {
  const root = tmp();
  write(root, 'en/index.html', page(`<h2 id="intro">Intro</h2><a href="/en/other/">other</a>${extra}`, options));
  write(root, 'sv/index.html', page('<a href="/en/">en</a>'));
  write(root, 'en/other/index.html', page('<h2 id="deep">Deep</h2>'));
  write(root, '404.html', page('<p>missing</p>', { hreflang: false }));
  return root;
}
const links = (root, ...args) => python('check-links.py', [root, '--site', 'https://example.test', ...args]);

test('check-links: a clean site passes', () => {
  const r = links(dist('<a href="/en/other/#deep">deep</a><a href="#intro">up</a><a href="mailto:a@b.test">m</a><a href="https://other.test/">x</a>'));
  assert.equal(r.status, 0, r.stderr);
});

test('check-links: a broken internal link fails and names the page and link', () => {
  const r = links(dist('<a href="/en/missing/">gone</a>'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /en\/index\.html.*\/en\/missing\/.*does not resolve/);
});

test('check-links: a relative link that leaves the page directory wrongly fails', () => {
  const r = links(dist('<a href="../pricing/">p</a>'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /\.\.\/pricing\//);
});

test('check-links: a broken anchor on another page fails', () => {
  const r = links(dist('<a href="/en/other/#nope">anchor</a>'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /missing anchor #nope on en\/other\/index\.html/);
});

test('check-links: a broken anchor on the same page fails', () => {
  const r = links(dist('<a href="#nope">anchor</a>'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /missing anchor #nope/);
});

test('check-links: an http: link and an http: script fail', () => {
  const r = links(dist('<a href="http://plain.test/">x</a><script src="http://plain.test/a.js"></script>'));
  assert.equal(r.status, 1);
  assert.equal((r.stderr.match(/only https is allowed/g) ?? []).length, 2);
});

test('check-links: a missing local script or image fails', () => {
  const r = links(dist('<script src="/_astro/gone.js"></script><img src="/img/gone.png" alt="">'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /gone\.js/);
  assert.match(r.stderr, /gone\.png/);
});

test('check-links: a page without hreflang for both languages fails, but 404.html is exempt', () => {
  const r = links(dist('', { hreflang: false }));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /en\/index\.html: missing hreflang for sv, en/);
  assert.doesNotMatch(r.stderr, /404\.html/);
});

test('check-links: a missing trailing slash is called out', () => {
  const r = links(dist('<a href="/en/other">other</a>'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /missing trailing slash/);
});

test('check-links: the base path is honoured', () => {
  const root = tmp();
  write(root, 'en/index.html', page('<a href="/docs/en/other/">ok</a><a href="/en/other/">outside base</a>'));
  write(root, 'sv/index.html', page(''));
  write(root, 'en/other/index.html', page(''));
  const r = links(root, '--base', '/docs');
  assert.equal(r.status, 1);
  assert.match(r.stderr, /\/en\/other\/.*outside the base path \/docs/);
  assert.doesNotMatch(r.stderr, /"\/docs\/en\/other\/"/);
});

test('check-links --external reports external links and still passes', () => {
  const r = links(dist('<a href="https://other.test/page">x</a>'), '--external');
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /https:\/\/other\.test\/page/);
});

// ---- check-pricing -------------------------------------------------------------------------------------------------

const pricingFile = path.join(site, 'src/data/pricing.json');
const realPricing = () => JSON.parse(fs.readFileSync(pricingFile, 'utf8'));
const pricing = (changes) => {
  const data = realPricing();
  changes(data);
  const file = path.join(tmp(), 'pricing.json');
  fs.writeFileSync(file, JSON.stringify(data));
  return python('check-pricing.py', ['--repo-root', repo, '--pricing', file]);
};

test('check-pricing: the committed prices agree with the licensing documents', () => {
  const r = python('check-pricing.py', []);
  assert.equal(r.status, 0, r.stderr);
});

test('check-pricing: a changed price fails and names the row', () => {
  const r = pricing((d) => (d.personal[3].amount = 55));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /12 month\(s\) 55 USD/);
  assert.match(r.stderr, /12 month\(s\) 32 USD/);
});

test('check-pricing: a removed tier and a changed organisation price fail', () => {
  const removed = pricing((d) => d.personal.pop());
  assert.equal(removed.status, 1);
  assert.match(removed.stderr, /60 month\(s\) 100 USD/);
  const org = pricing((d) => (d.org.amount = 900));
  assert.equal(org.status, 1);
  assert.match(org.stderr, /org\.amount is 900/);
});

test('check-pricing: a longer personal period must be cheaper per month and cost more in total', () => {
  const flat = pricing((d) => (d.personal[3].amount = 36));
  assert.equal(flat.status, 1);
  assert.match(flat.stderr, /Personal 12 months \(3\.00\/month\) must cost strictly less per month than 6 month\(s\)/);
  const cheaper = pricing((d) => (d.personal[2].amount = 9));
  assert.equal(cheaper.status, 1);
  assert.match(cheaper.stderr, /Personal 6 months \(9\) must cost more in total than 3 month\(s\) \(10\)/);
});

test('check-pricing: a buy URL must be empty or https on Polar', () => {
  assert.doesNotMatch(pricing((d) => (d.personal[0].buyUrl = 'https://buy.polar.sh/abc')).stderr, /must be empty or an https/);
  const bad = pricing((d) => (d.personal[0].buyUrl = 'http://shop.example/abc'));
  assert.equal(bad.status, 1);
  assert.match(bad.stderr, /must be empty or an https:\/\/ URL on Polar/);
  const elsewhere = pricing((d) => (d.storeUrl = 'https://shop.example/abc'));
  assert.equal(elsewhere.status, 1);
  assert.match(elsewhere.stderr, /storeUrl/);
});

test('check-pricing: the app buy URL and the site must agree', () => {
  const root = tmp();
  for (const f of ['docs/explanation/licensing.md', 'docs/explanation/licensing.sv.md']) {
    if (fs.existsSync(path.join(repo, f))) write(root, f, fs.readFileSync(path.join(repo, f), 'utf8'));
  }
  const app = (url) => write(root, 'frontend/src/features/mcp-apps/license-state.ts', `export const LICENSE_BUY_URL = "${url}";\n`);
  const run = (data) => {
    const file = path.join(tmp(), 'pricing.json');
    fs.writeFileSync(file, JSON.stringify({ ...realPricing(), ...data }));
    return python('check-pricing.py', ['--repo-root', root, '--pricing', file]);
  };
  app('');
  assert.equal(run({}).status, 0);
  app('https://buy.polar.sh/shop');
  const mismatch = run({});
  assert.equal(mismatch.status, 1);
  assert.match(mismatch.stderr, /LICENSE_BUY_URL/);
  assert.equal(run({ storeUrl: 'https://buy.polar.sh/shop' }).status, 0);
  assert.equal(run({ storeUrl: 'https://buy.polar.sh/other' }).status, 1);
  app('https://roadlake.example/en/buy/');
  assert.equal(run({ storeUrl: 'https://buy.polar.sh/shop' }).status, 0);
});

// ---- html-validate ---------------------------------------------------------------------------------------------------

test('html-validate: a stray element name and a duplicate id fail with the site configuration', () => {
  const root = tmp();
  fs.copyFileSync(path.join(site, '.htmlvalidate.json'), path.join(root, '.htmlvalidate.json'));
  write(root, 'ok.html', '<!DOCTYPE html><html lang="en"><head><title>t</title></head><body><main><h1>x</h1></main></body></html>');
  write(root, 'bad.html', '<!DOCTYPE html><html lang="en"><head><title>t</title></head><body><main><h1 id="a">x</h1><p id="a">Connect to <your server>?</p></main></body></html>');
  const bin = path.join(site, 'node_modules/.bin/html-validate');
  const run = (file) => spawnSync(bin, ['-c', path.join(root, '.htmlvalidate.json'), path.join(root, file)], { encoding: 'utf8' });
  assert.equal(run('ok.html').status, 0, run('ok.html').stdout);
  const bad = run('bad.html');
  assert.notEqual(bad.status, 0);
  assert.match(bad.stdout, /element-name|no-dup-id/);
});
