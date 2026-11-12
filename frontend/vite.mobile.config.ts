import { renameSync } from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { MOBILE_BANNER } from "./vite.license-banner";

// The mobile entry (mobile.html + src/mobile/main.tsx) for the Capacitor shell: local, release-packaged assets in
// dist-mobile/ with relative URLs. Separate from the MCP App bundle (vite.mcp-app.config.ts), which it does not touch.
// Real React here (the MCP bundle's Preact alias is a size measure for a resource Claude downloads; this is shipped
// inside the app). Capacitor's webDir looks for index.html, so the entry is written under that name.
export default defineConfig({
  base: "./",
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  plugins: [
    react(),
    {
      name: "sidekick-mobile-index",
      // After the files are written, not by editing the bundle (Rolldown does not support that).
      writeBundle(options) {
        const dir =
          options.dir ?? path.resolve(import.meta.dirname, "dist-mobile");
        renameSync(path.join(dir, "mobile.html"), path.join(dir, "index.html"));
      },
    },
  ],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  build: {
    outDir: "dist-mobile",
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(import.meta.dirname, "mobile.html"),
      // React, Capacitor and the other MIT libraries must keep their notice, which minifying would drop. Once, in the
      // entry chunk: the lazy chunks are parts of the same bundle.
      output: { postBanner: (chunk) => (chunk.isEntry ? MOBILE_BANNER : "") },
    },
    // The app's minimum WebView is Chromium 123, the first with light-dark(), which the rooms' CSS keeps native (see
    // vite.mcp-app.config.ts). These two targets, MIN_CHROMIUM_MAJOR in android/app/.../WebViewRequirement.kt and
    // minWebViewVersion in capacitor.config.ts must name the same number; WebViewRequirementTest fails when they differ.
    // The app has no browserslist: this target is the only place the web side states a browser floor.
    target: "chrome123",
    cssTarget: "chrome123",
    sourcemap: false,
  },
});
