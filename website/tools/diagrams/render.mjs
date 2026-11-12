// Pre-renders the Mermaid blocks of the documentation to SVG (light and dark), named by the hash of the block.
// Usage: npm --prefix website/tools/diagrams ci --ignore-scripts && npm --prefix website/tools/diagrams run render
// Needs a Playwright Chromium (npx playwright install chromium). The SVGs are committed to src/assets/diagrams/.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createMermaidRenderer } from 'mermaid-isomorphic';

const here = path.dirname(fileURLToPath(import.meta.url));
const websiteDir = path.resolve(here, '..', '..');
const { collectMermaid } = await import(pathToFileURL(path.join(websiteDir, 'scripts/sync-docs.mjs')).href);
const map = await import(pathToFileURL(path.join(websiteDir, 'content-map.mjs')).href);

const sourceRoot = process.env.SITE_SOURCE_ROOT ?? path.resolve(websiteDir, '..');
const outDir = path.join(websiteDir, 'src/assets/diagrams');
fs.mkdirSync(outDir, { recursive: true });

const blocks = collectMermaid(sourceRoot, map);
const renderer = createMermaidRenderer();
let rendered = 0;
for (const [hash, { code, rel }] of blocks) {
  for (const [mode, theme] of [['light', 'neutral'], ['dark', 'dark']]) {
    const file = path.join(outDir, `${hash}.${mode}.svg`);
    if (fs.existsSync(file) && !process.argv.includes('--force')) continue;
    const [result] = await renderer([code], { mermaidConfig: { theme, fontFamily: 'system-ui, sans-serif' } });
    if (result.status !== 'fulfilled') throw new Error(`${rel}: mermaid failed for ${hash}: ${result.reason}`);
    fs.writeFileSync(file, result.value.svg + '\n');
    rendered++;
  }
}
console.log(`diagrams: ${blocks.size} blocks, ${rendered} files written to ${outDir}`);
