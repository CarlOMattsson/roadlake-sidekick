#!/usr/bin/env node
// Turns the repository's Markdown documents into Starlight pages (docs/ia.md in the design: one source of truth).
// Only node:* modules. Output is git-ignored: src/content/docs/{en,sv}/docs/** and public/docs-images/**.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const websiteDir = path.resolve(here, '..');
const OVERLAY = 'tools/export/overlay';
const IMAGE_EXT = /\.(png|jpe?g|gif|svg|webp|avif)$/i;
const LANG_ROW_WORDS = new Set(['svenska', 'english', 'documentation', 'dokumentation']);

// ---------- small helpers ----------

export function slugify(segment) {
  return segment
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\p{M}_\- ]/gu, '')
    .replace(/ /g, '-');
}

export function diagramHash(block) {
  const text = block.replace(/\r\n/g, '\n').replace(/\s+$/, '');
  return crypto.createHash('sha256').update(text).digest('hex').slice(0, 12);
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
// HTML elements that may appear as raw HTML in the sources. Any other "<word ...>" outside code is prose (a placeholder such as
// "<your server>") and is escaped, otherwise the browser reads it as an element and breaks the page.
const HTML_TAGS = new Set(
  'a abbr b blockquote br caption code col colgroup dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p picture pre q s samp small source span strong sub summary sup table tbody td tfoot th thead tr u ul var'.split(' '),
);
export function escapeProsePlaceholders(text) {
  return text.replace(/<(?!\/?([A-Za-z][A-Za-z0-9]*)(?=[\s/>])|!--|[A-Za-z][A-Za-z0-9+.-]*:[^\s>]*>|[^\s>@]+@[^\s>]+>)/g, '&lt;').replace(
    /<\/?([A-Za-z][A-Za-z0-9]*)(?=[\s/>])/g,
    (m, name) => (HTML_TAGS.has(name.toLowerCase()) ? m : `&lt;${m.slice(1)}`),
  );
}
const yamlStr = (s) => JSON.stringify(s);

/** Truncate at a word end so the result is at most `max` characters. */
export function truncateWords(text, max = 160) {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const at = cut.lastIndexOf(' ');
  return (at > 40 ? cut.slice(0, at) : cut).replace(/[\s.,;:]+$/, '') + '…';
}

function stripMarkdown(text) {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// ---------- source access (overlay first, then the root) ----------

function makeSource(root) {
  const resolve = (rel) => {
    for (const base of [path.join(root, OVERLAY), root]) {
      const abs = path.join(base, rel);
      if (fs.existsSync(abs)) return abs;
    }
    return null;
  };
  const walk = (relDir) => {
    const out = new Set();
    for (const base of [path.join(root, OVERLAY), root]) {
      const start = path.join(base, relDir);
      if (!fs.existsSync(start)) continue;
      const stack = [start];
      while (stack.length) {
        const dir = stack.pop();
        for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
          const abs = path.join(dir, ent.name);
          if (ent.isDirectory()) {
            if (ent.name === 'node_modules' || ent.name.startsWith('.')) continue;
            stack.push(abs);
          } else out.add(path.relative(base, abs).split(path.sep).join('/'));
        }
      }
    }
    return [...out].sort();
  };
  return { root, resolve, walk, exists: (rel) => resolve(rel) !== null, isDir: (rel) => !!resolve(rel) && fs.statSync(resolve(rel)).isDirectory() };
}

function stemOf(rel) {
  return rel.replace(/\.sv\.md$/, '').replace(/\.md$/, '');
}

function matches(rel, entry) {
  const stem = stemOf(rel);
  if (entry.endsWith('/')) return stem.startsWith(entry);
  return stem === entry.replace(/\.md$/, '');
}

// ---------- discovery ----------

export function discover(source, map) {
  const include = map.include ?? ['docs/'];
  const exclude = map.exclude ?? [];
  const pages = [];
  const add = (rel, slug, root, description) => {
    const locale = rel.endsWith('.sv.md') ? 'sv' : 'en';
    pages.push({ rel, stem: stemOf(rel), locale, slug, isRoot: root, description, url: slug.replace(/(^|\/)index$/, '') });
  };
  for (const rel of source.walk('docs')) {
    if (!rel.endsWith('.md')) continue;
    if (exclude.some((e) => matches(rel, e))) continue;
    if (!include.some((i) => matches(rel, i))) continue;
    const segs = stemOf(rel).split('/').map((s, i, a) => (i === a.length - 1 && s === 'README' ? 'index' : slugify(s)));
    add(rel, segs.join('/'), false);
  }
  for (const rf of map.rootFiles ?? []) {
    for (const rel of [`${rf.src}.md`, `${rf.src}.sv.md`]) if (source.exists(rel)) add(rel, rf.slug, true, rf.description);
  }
  const seen = new Map();
  for (const p of pages) {
    const key = `${p.locale}:${p.slug}`;
    if (seen.has(key)) throw new Error(`Two sources map to the same page ${key}: ${seen.get(key)} and ${p.rel}`);
    seen.set(key, p.rel);
  }
  return pages;
}

// ---------- Markdown transformation ----------

/** Splits text into lines tagged as code (fenced) or text. Returns blocks of {fence, lines}. */
function splitFences(lines) {
  const blocks = [];
  let cur = { code: false, lines: [] };
  let fence = null;
  for (const line of lines) {
    const m = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (!fence && m) {
      blocks.push(cur);
      cur = { code: true, info: m[2].trim(), open: line, lines: [] };
      fence = { ch: m[1][0], len: m[1].length };
    } else if (fence && m && m[1][0] === fence.ch && m[1].length >= fence.len && m[2].trim() === '') {
      cur.close = line;
      blocks.push(cur);
      cur = { code: false, lines: [] };
      fence = null;
    } else cur.lines.push(line);
  }
  blocks.push(cur);
  return blocks.filter((b) => b.code || b.lines.length);
}

function maskInlineCode(line) {
  const saved = [];
  const masked = line.replace(/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g, (m) => {
    saved.push(m);
    return `\u0000${saved.length - 1}\u0000`;
  });
  return { masked, restore: (s) => s.replace(/\u0000(\d+)\u0000/g, (_, i) => saved[Number(i)]) };
}

export function run(opts = {}) {
  const map = opts.map;
  const sourceRoot = path.resolve(opts.sourceRoot);
  const outDir = path.resolve(opts.outDir ?? websiteDir);
  const diagramsDir = path.resolve(opts.diagramsDir ?? path.join(websiteDir, 'src/assets/diagrams'));
  const base = opts.base ?? '';
  const repoUrl = opts.repoUrl ?? 'https://github.com/CarlOMattsson/roadlake-sidekick';
  const source = makeSource(sourceRoot);
  const errors = [];
  const warnings = [];

  // --verify-sources: every source named in the map must exist. Writes nothing.
  const missing = [];
  for (const e of map.include ?? []) {
    const ok = e.endsWith('/') ? source.isDir(e.slice(0, -1)) : source.exists(`${e}.md`) || source.exists(`${e}.sv.md`);
    if (!ok) missing.push(`include: ${e}`);
  }
  for (const rf of map.rootFiles ?? []) {
    if (!source.exists(`${rf.src}.md`) && !source.exists(`${rf.src}.sv.md`)) missing.push(`rootFiles: ${rf.src}`);
  }
  const pages = discover(source, map);
  const urls = new Set(pages.map((p) => p.url));
  for (const [dir, names] of Object.entries(map.order ?? {})) {
    for (const n of names) if (!urls.has(`${dir}/${n}`.replace(/\/index$/, ''))) missing.push(`order: ${dir}/${n}`);
  }
  for (const slug of Object.keys(map.titles ?? {})) if (!urls.has(slug.replace(/\/index$/, ''))) missing.push(`titles: ${slug}`);
  for (const a of map.assets ?? []) if (!source.isDir(a.replace(/\/$/, ''))) missing.push(`assets: ${a}`);
  for (const gen of Object.keys(map.generated ?? {})) if (!urls.has(gen)) missing.push(`generated: ${gen}`);
  if (opts.verifyOnly) return { pages, missing, errors: missing.map((m) => `Missing source in content-map.mjs: ${m}`), warnings };
  errors.push(...missing.map((m) => `Missing source in content-map.mjs: ${m}`));

  const pageByKey = new Map(pages.map((p) => [`${p.locale}:${p.stem}`, p]));
  const copiedImages = new Map();
  const usedDiagrams = new Set();
  const outputs = [];

  const pageFor = (stem, locale) => (locale === 'sv' ? pageByKey.get(`sv:${stem}`) : null) ?? pageByKey.get(`en:${stem}`) ?? null;

  const relUrl = (fromUrl, toUrl) => {
    const rel = path.posix.relative(fromUrl || '.', toUrl || '.');
    return rel === '' ? './' : `${rel}/`;
  };

  function imageUrl(rel) {
    const dest = rel.replace(/^docs\/images\//, '').replace(/^docs\//, '');
    copiedImages.set(rel, dest);
    return `${base}/docs-images/${dest}`;
  }

  function rewriteTarget(url, page) {
    if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//') || url.startsWith('#') || url === '') return url;
    const m = url.match(/^([^#?]*)([?#].*)?$/);
    const rawPath = decodeURI(m[1]);
    const tail = m[2] ?? '';
    const from = path.posix.dirname(page.rel);
    const target = (rawPath.startsWith('/') ? rawPath.slice(1) : path.posix.join(from, rawPath)).replace(/\/$/, '');
    if (target.startsWith('..')) {
      warnings.push(`${page.rel}: link leaves the repository: ${url}`);
      return url;
    }
    if (target.endsWith('.md')) {
      const hit = pageFor(stemOf(target), page.locale);
      if (hit) return relUrl(page.url, hit.url) + tail.replace(/^\?.*?(#|$)/, '$1');
    }
    if (source.isDir(target)) {
      const idx = pageFor(`${target}/README`, page.locale);
      if (idx) return relUrl(page.url, idx.url) + tail;
      return `${repoUrl}/tree/main/${target}${tail}`;
    }
    if (source.exists(target)) {
      if (IMAGE_EXT.test(target)) return imageUrl(target) + tail;
      return `${repoUrl}/blob/main/${target}${tail}`;
    }
    warnings.push(`${page.rel}: link target not found: ${url}`);
    return `${repoUrl}/blob/main/${target}${tail}`;
  }

  function transformInline(line, page, lineNo) {
    const { masked, restore } = maskInlineCode(line);
    const rewriteMd = (text) =>
      text.replace(/(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)((?:\s+"[^"]*")?)\)/g, (_, bang, label, url, title) => {
        if (bang && label.trim() === '') errors.push(`${page.rel}:${lineNo}: image without alt text: ${url}`);
        const inner = bang ? label : rewriteMd(label);
        return `${bang}[${inner}](${rewriteTarget(url, page)}${title})`;
      });
    let out = rewriteMd(masked);
    out = out.replace(/^(\s*\[[^\]]+\]:\s*)(\S+)/, (_, pre, url) => pre + rewriteTarget(url, page));
    out = out.replace(/<(a|img)\b[^>]*>/gi, (tag, name) => {
      if (name.toLowerCase() === 'img' && !/\balt\s*=/.test(tag)) errors.push(`${page.rel}:${lineNo}: <img> without alt attribute`);
      return tag.replace(/\b(href|src)=("([^"]*)"|'([^']*)')/g, (all, attr, q, d, s) => `${attr}="${esc(rewriteTarget((d ?? s).replace(/&amp;/g, '&'), page)).replace(/&amp;/g, '&')}"`);
    });
    return restore(escapeProsePlaceholders(out));
  }

  function renderMermaid(code, page) {
    const hash = diagramHash(code);
    const title = code.match(/^\s*accTitle:\s*(.+)$/m)?.[1]?.trim() ?? map.diagramText?.[hash]?.title;
    const descr =
      code.match(/^\s*accDescr:\s*(.+)$/m)?.[1]?.trim() ??
      code.match(/accDescr\s*\{([^}]*)\}/)?.[1]?.replace(/\s+/g, ' ').trim() ??
      map.diagramText?.[hash]?.descr;
    if (!title || !descr) {
      errors.push(`${page.rel}: mermaid block ${hash} needs accTitle: and accDescr: (alt text and caption). Add them to the block.`);
      return null;
    }
    for (const mode of ['light', 'dark']) {
      if (!fs.existsSync(path.join(diagramsDir, `${hash}.${mode}.svg`))) {
        errors.push(
          `${page.rel}: no rendered diagram for mermaid block ${hash} (${mode}). Render it with: npm --prefix website/tools/diagrams ci --ignore-scripts && npm --prefix website/tools/diagrams run render`,
        );
        return null;
      }
    }
    usedDiagrams.add(hash);
    const img = (mode) => `<img class="diagram-${mode}" src="${base}/docs-images/diagrams/${hash}.${mode}.svg" alt="${esc(title)}" loading="lazy">`;
    return `<figure class="diagram">\n${img('light')}\n${img('dark')}\n<figcaption>${esc(descr)}</figcaption>\n</figure>`;
  }

  function convert(page) {
    const raw = fs.readFileSync(source.resolve(page.rel), 'utf8').replace(/\r\n/g, '\n');
    const lines = raw.split('\n');
    const blocks = splitFences(lines);

    // 1. Title: first "# H1" outside code.
    let title = null;
    let description = null;
    let h1Seen = false;
    let afterH1 = false;
    let langRowChecked = false;
    let descFallback = null;
    const outLines = [];
    let lineNo = 0;
    for (const block of blocks) {
      if (block.code) {
        lineNo += block.lines.length + 2;
        if (block.info.split(/\s+/)[0] === 'mermaid') {
          const fig = renderMermaid(block.lines.join('\n'), page);
          if (fig) outLines.push(fig);
        } else {
          outLines.push(block.open, ...block.lines, block.close ?? '');
        }
        afterH1 = false;
        continue;
      }
      const lines2 = block.lines;
      for (let i = 0; i < lines2.length; i++) {
        lineNo++;
        const line = lines2[i];
        if (!h1Seen && /^# +\S/.test(line)) {
          h1Seen = true;
          afterH1 = true;
          title = stripMarkdown(line.replace(/^# +/, '').replace(/\s+#*$/, ''));
          continue;
        }
        if (afterH1) {
          if (line.trim() === '') continue;
          const dm = line.match(/^<!--\s*description:\s*([\s\S]*?)\s*-->\s*$/);
          if (dm && description === null) {
            description = dm[1].trim();
            continue;
          }
          if (!langRowChecked) {
            langRowChecked = true;
            // A paragraph of nothing but links separated by " · " with a language/documentation link is dropped.
            let j = i;
            const para = [];
            while (j < lines2.length && lines2[j].trim() !== '') para.push(lines2[j++]);
            const joined = para.join(' ').trim();
            const rowRe = /^\[[^\]]+\]\([^)]+\)(\s*·\s*\[[^\]]+\]\([^)]+\))*$/;
            if (rowRe.test(joined)) {
              const texts = [...joined.matchAll(/\[([^\]]+)\]/g)].map((x) => x[1].trim().toLowerCase());
              if (texts.some((t) => LANG_ROW_WORDS.has(t))) {
                lineNo += para.length - 1;
                i = j - 1;
                continue;
              }
            }
          }
          if (line.trim() !== '') afterH1 = false;
        }
        if (h1Seen && descFallback === null && !afterH1) {
          // First plain paragraph after the title: collect once.
          if (line.trim() && !/^(#|>|[-*+] |\d+\.\s|\||<|\s{4})/.test(line)) {
            const para = [line];
            let j = i + 1;
            while (j < lines2.length && lines2[j].trim() !== '') para.push(lines2[j++]);
            descFallback = stripMarkdown(para.join(' '));
          }
        }
        outLines.push(transformInline(line, page, lineNo));
      }
    }
    if (!title) title = page.stem.split('/').pop();
    if (!description) description = page.description ?? truncateWords(descFallback ?? '', 160);
    return { title, description, body: outLines.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n' };
  }

  // ---------- generate ----------
  const orderOf = (page) => {
    const dir = path.posix.dirname(page.slug);
    const name = path.posix.basename(page.slug);
    const list = map.order?.[dir === '.' ? '' : dir];
    const idx = list ? list.indexOf(name) : -1;
    return idx >= 0 ? idx + 1 : null;
  };

  for (const page of pages) {
    const converted = convert(page);
    const { description, body } = converted;
    const title = map.titles?.[page.slug]?.[page.locale] ?? converted.title;
    const order = orderOf(page);
    const fm = ['---', `title: ${yamlStr(title)}`, `description: ${yamlStr(description)}`];
    if (order !== null) fm.push('sidebar:', `  order: ${order}`);
    fm.push('lastUpdated: false', '---', '');
    outputs.push({ file: path.join(outDir, 'src/content/docs', page.locale, `${page.slug}.md`), text: fm.join('\n') + '\n' + body });
  }

  if (errors.length) return { pages, errors, warnings, missing };

  for (const dir of ['en', 'sv']) fs.rmSync(path.join(outDir, 'src/content/docs', dir, 'docs'), { recursive: true, force: true });
  fs.rmSync(path.join(outDir, 'public/docs-images'), { recursive: true, force: true });
  for (const o of outputs) {
    fs.mkdirSync(path.dirname(o.file), { recursive: true });
    fs.writeFileSync(o.file, o.text);
  }
  for (const dir of map.assets ?? []) {
    for (const rel of source.walk(dir.replace(/\/$/, ''))) {
      if (IMAGE_EXT.test(rel)) copiedImages.set(rel, rel.replace(/^docs\/images\//, '').replace(/^docs\//, ''));
    }
  }
  for (const [rel, dest] of copiedImages) {
    const to = path.join(outDir, 'public/docs-images', dest);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(source.resolve(rel), to);
  }
  for (const hash of usedDiagrams) {
    for (const mode of ['light', 'dark']) {
      const to = path.join(outDir, 'public/docs-images/diagrams', `${hash}.${mode}.svg`);
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(path.join(diagramsDir, `${hash}.${mode}.svg`), to);
    }
  }
  return { pages, errors, warnings, missing, written: outputs.length, images: copiedImages.size };
}

/** All mermaid blocks in the rendered sources, for tools/diagrams/render.mjs. */
export function collectMermaid(sourceRoot, map) {
  const source = makeSource(path.resolve(sourceRoot));
  const found = new Map();
  for (const page of discover(source, map)) {
    const text = fs.readFileSync(source.resolve(page.rel), 'utf8').replace(/\r\n/g, '\n');
    for (const block of splitFences(text.split('\n'))) {
      if (block.code && block.info.split(/\s+/)[0] === 'mermaid') found.set(diagramHash(block.lines.join('\n')), { code: block.lines.join('\n'), rel: page.rel });
    }
  }
  return found;
}

// ---------- CLI ----------

function arg(argv, name) {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : undefined;
}

async function main(argv) {
  const { SITE_BASE, REPO_URL } = await import('../site-config.mjs');
  const mapPath = arg(argv, '--map') ?? path.join(websiteDir, 'content-map.mjs');
  const map = await import(pathToFileURL(path.resolve(mapPath)).href);
  const sourceRoot = arg(argv, '--source-root') ?? process.env.SITE_SOURCE_ROOT ?? path.resolve(websiteDir, '..');
  const result = run({
    map,
    sourceRoot,
    base: SITE_BASE,
    repoUrl: REPO_URL,
    outDir: arg(argv, '--out'),
    verifyOnly: argv.includes('--verify-sources'),
  });
  for (const w of result.warnings) console.warn(`warning: ${w}`);
  if (result.errors.length) {
    for (const e of result.errors) console.error(`error: ${e}`);
    return 1;
  }
  console.log(argv.includes('--verify-sources') ? `sources ok (${result.pages.length} pages)` : `sync: ${result.written} pages, ${result.images} images from ${sourceRoot}`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main(process.argv.slice(2));
}
