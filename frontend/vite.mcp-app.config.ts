import path from "node:path";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { gzipSync } from "node:zlib";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { PREACT_COMPAT_ALIASES } from "./vite.mcp-app-alias";
import { MCP_APP_BANNER } from "./vite.license-banner";

// One self-contained resource for the whole Sidekick app: no CDN, external asset or connect permission.
// All four resources (work, journal, shopping, control) serve this file; the router in the bundle
// picks the room. Build it with `vite build --config vite.mcp-app.config.ts --mode sidekick`.
const apps = {
  sidekick: {
    title: "Sidekick",
    entry: "src/features/mcp-apps/sidekick-entry.tsx",
    libName: "Sidekick",
  },
};
// Our own guard rail for the finished HTML (gzip -9), not a host limit. Load time is guarded by perf-mcp-app.spec.ts.
const GZIP_BUDGET_BYTES = 200 * 1024;
type AppName = keyof typeof apps;

const LOCALES = ["sv", "en"] as const;
/**
 * The room names of the strip and the loading line by app language. Keep in step with the shell labels
 * (sidekick-shell-labels.ts) and `awaitingSv`/`awaitingEn` in awaiting.tsx; tests/awaiting.test.tsx checks the built document.
 */
const WAIT_TEXT = {
  sv: { rooms: ["Arbete", "Dagbok", "Kontakter", "Inköp"], loading: "Laddar…" },
  en: {
    rooms: ["Work", "Journal", "Contacts", "Shopping"],
    loading: "Loading…",
  },
} as const;
/**
 * Sets the document language from the `sidekick-app-locale` meta the server writes into the head
 * (app-locale.ts does the same on start, Swedish when the meta is missing), so the placeholder can
 * show the app language before the bundle has run.
 */
const LOCALE_SCRIPT = `<script>document.documentElement.lang=(document.querySelector('meta[name="sidekick-app-locale"]')||{}).content==="en"?"en":"sv"</script>`;
/** Shows the placeholder texts of the document language only. */
const LOCALE_CSS = `html[lang="en"] [data-wait-locale="sv"],html[lang="sv"] [data-wait-locale="en"]{display:none}`;

/**
 * The placeholder shown before the host answers: awaiting.css (minified) and the markup of AwaitingResult in
 * awaiting.tsx, so the app takes it over in place. Keep the markup in step with awaiting.tsx, class for class.
 * Its texts exist in both app languages and the document language (LOCALE_SCRIPT) picks one, because the app
 * language is an instance setting that the static document does not know.
 */
function waitPlaceholder() {
  const waitCss = readFileSync(
    path.resolve(import.meta.dirname, "src/features/mcp-apps/awaiting.css"),
    "utf8",
  )
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\s+/g, " ")
    .replace(/\s*([{};,:])\s*/g, "$1")
    .trim();
  const block = (extra: string) =>
    `<span class="sidekick-wait-block ${extra}"></span>`;
  // One and two title lines alternate, as SkeletonRows draws them.
  const row = (lines: number) =>
    `<div class="sidekick-wait-row">${block("sidekick-wait-glyph")}<span class="sidekick-wait-text">${block("sidekick-wait-row-title").repeat(lines)}${block("sidekick-wait-meta")}</span></div>`;
  // The room is not known before the host has answered: no room is marked and no room's header is drawn.
  const strip = (locale: (typeof LOCALES)[number]) => {
    const names = WAIT_TEXT[locale].rooms
      .map((room) => `<span class="sidekick-wait-room">${room}</span>`)
      .join("");
    return `<div aria-hidden="true" class="sidekick-wait-strip" data-wait-locale="${locale}">${names}</div>`;
  };
  const line = (locale: (typeof LOCALES)[number]) =>
    `<p class="sidekick-wait-line" data-wait-locale="${locale}">${WAIT_TEXT[locale].loading}</p>`;
  const waitMarkup =
    `<div class="sidekick-wait" role="status" aria-busy="true" data-frame="full">` +
    LOCALES.map(strip).join("") +
    LOCALES.map(line).join("") +
    `<div aria-hidden="true" class="sidekick-wait-rows">${(row(1) + row(2)).repeat(2)}</div>` +
    `</div>`;
  return { waitCss, waitMarkup };
}

function isAppName(mode: string): mode is AppName {
  return Object.keys(apps).includes(mode);
}

export default defineConfig(({ mode }) => {
  if (!isAppName(mode))
    throw new Error(
      `Unknown MCP App mode "${mode}"; use --mode ${Object.keys(apps).join(" or ")}`,
    );
  const app = apps[mode];
  return {
    define: {
      "process.env.NODE_ENV": JSON.stringify("production"),
    },
    plugins: [
      react(),
      {
        name: "sidekick-mcp-app-resource",
        // writeBundle, not generateBundle: Vite's CSS plugin emits the stylesheet asset in its
        // own generateBundle, which can run after this one and left the inlined <style> empty.
        writeBundle(_options, bundle) {
          const chunks = Object.values(bundle).filter(
            (entry) => entry.type === "chunk",
          );
          if (chunks.length !== 1)
            throw new Error("MCP App must have exactly one script");
          const css = Object.values(bundle)
            .flatMap((entry) =>
              entry.type === "asset" && entry.fileName.endsWith(".css")
                ? [entry.source]
                : [],
            )
            .join("\n");
          if (!css.trim())
            throw new Error(`MCP App "${mode}" has no stylesheet to inline`);
          const script = chunks[0].code.replace(/<\/script/gi, "<\\/script");
          // Order matters for the first paint: small style and placeholder first, then the stylesheet, then the script.
          const { waitCss, waitMarkup } = waitPlaceholder();
          const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>${app.title}</title>${LOCALE_SCRIPT}<style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0;background:transparent}body{color:light-dark(#222,#eee);font-family:var(--font-sans,system-ui,sans-serif);line-height:1.4}button,input,select,textarea{font:inherit;color:inherit}${waitCss}${LOCALE_CSS}</style></head><body><div id="root">${waitMarkup}</div><style>${css}</style><script>${script}</script></body></html>\n`;
          const dir = path.resolve(
            import.meta.dirname,
            "../backend/src/sidekick/mcp/apps",
          );
          mkdirSync(dir, { recursive: true });
          const gzipBytes = gzipSync(html, { level: 9 }).length;
          const budget = GZIP_BUDGET_BYTES;
          if (gzipBytes > budget)
            throw new Error(
              `MCP App "${mode}" is ${gzipBytes} bytes gzipped; the budget is ${budget}`,
            );
          writeFileSync(path.join(dir, `${mode}.html`), html);
          console.log(
            `MCP App "${mode}": ${html.length} bytes, ${gzipBytes} bytes gzip -9 (budget ${budget})`,
          );
        },
      },
    ],
    resolve: {
      alias: [
        { find: "@", replacement: path.resolve(import.meta.dirname, "src") },
        // Why: the app is downloaded every time a card opens, so the bundle uses Preact's compat layer, which is much
        // smaller. Its events and batching differ in small ways (native events, microtask-batched updates, flushSync
        // emulated; board-card.tsx relies on it). The Playwright specs run this bundle; Vitest covers the same source on
        // React, and `npm run test:mcp-app:preact` reruns the view tests with these same aliases (npm run check includes it), and the mobile shell (vite.mobile.config.ts) keeps real React.
        ...PREACT_COMPAT_ALIASES,
      ],
    },
    build: {
      minify: true,
      outDir: `dist-mcp-app/${mode}`,
      lib: {
        entry: app.entry,
        name: app.libName,
        formats: ["iife"],
        fileName: () => `${mode}.js`,
      },
      // The bundled Preact (MIT) must keep its notice, which minifying would drop; THIRD_PARTY_NOTICES.md has the rest.
      rollupOptions: { output: { postBanner: MCP_APP_BANNER } },
      cssCodeSplit: false,
      // Hosts are evergreen browsers with native light-dark(); an older target makes the CSS
      // minifier lower light-dark() to --lightningcss-* variables that nothing defines.
      cssTarget: ["chrome123", "safari17.5", "firefox120"],
      sourcemap: false,
    },
  };
});
