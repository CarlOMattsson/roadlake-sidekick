// Minimal static server for dist/, used by Playwright's webServer. `astro preview` detaches into a background
// process in agent environments, which leaves a server behind; this one stays in the foreground and exits with its parent.
// Honors SITE_BASE like the build does. Usage: node scripts/serve-dist.mjs [port]
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const port = Number(process.argv[2] ?? 4321);
const base = ('/' + (process.env.SITE_BASE ?? '').replace(/^\/+|\/+$/g, '')).replace(/^\/$/, '');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.xml': 'application/xml', '.txt': 'text/plain', '.wasm': 'application/wasm', '.webmanifest': 'application/manifest+json', '.pf_meta': 'application/octet-stream' };

http
  .createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    let rel = decodeURIComponent(url.pathname);
    if (base && !rel.startsWith(base + '/') && rel !== base) return notFound(res);
    rel = rel.slice(base.length) || '/';
    let file = path.join(dist, rel);
    if (!file.startsWith(dist)) return notFound(res);
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!fs.existsSync(file)) return notFound(res);
    res.writeHead(200, { 'content-type': types[path.extname(file)] ?? 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  })
  .listen(port, 'localhost', () => console.log(`serving ${dist} on http://localhost:${port}${base}/`));

function notFound(res) {
  const page = path.join(dist, '404.html');
  res.writeHead(404, { 'content-type': 'text/html; charset=utf-8' });
  res.end(fs.existsSync(page) ? fs.readFileSync(page) : 'Not found');
}
