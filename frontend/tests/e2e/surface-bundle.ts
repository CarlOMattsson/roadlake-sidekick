import path from "node:path";

import type { Locator } from "@playwright/test";
import react from "@vitejs/plugin-react";
import { build, type Rollup } from "vite";

import { PREACT_COMPAT_ALIASES } from "../../vite.mcp-app-alias";

// A test surface for shared components that no view uses yet: `entry` (a .tsx under tests/e2e) is built with Vite and
// the bundle's Preact aliases into one script and one stylesheet, which a spec loads into a blank page. No host, no
// bridge, no backend: a measurement in a real Chromium, neither a Claude nor an Android test.

const FRONTEND = path.resolve(import.meta.dirname, "../..");

export type SurfaceBundle = { js: string; css: string };

export async function buildSurface(entry: string): Promise<SurfaceBundle> {
  const output = (await build({
    configFile: false,
    root: FRONTEND,
    logLevel: "error",
    plugins: [react()],
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    resolve: {
      alias: [
        { find: "@", replacement: path.join(FRONTEND, "src") },
        ...PREACT_COMPAT_ALIASES,
      ],
    },
    build: {
      write: false,
      minify: false,
      copyPublicDir: false,
      lib: {
        entry: path.join(FRONTEND, "tests/e2e", entry),
        formats: ["iife"],
        name: "TestSurface",
        fileName: () => "surface.js",
      },
    },
  })) as Rollup.RollupOutput | Rollup.RollupOutput[];
  const files = (Array.isArray(output) ? output : [output]).flatMap(
    (result) => result.output,
  );
  return {
    js: files
      .filter((file): file is Rollup.OutputChunk => file.type === "chunk")
      .map((chunk) => chunk.code)
      .join("\n"),
    css: files
      .filter(
        (file): file is Rollup.OutputAsset =>
          file.type === "asset" && file.fileName.endsWith(".css"),
      )
      .map((asset) => String(asset.source))
      .join("\n"),
  };
}

/** The element's box, rounded to 1/100 px so a subpixel layout (47.99998) reads as the 48 it is. */
export async function box(locator: Locator) {
  const rect = await locator.evaluate((node) => {
    const r = node.getBoundingClientRect();
    return {
      x: r.x,
      y: r.y,
      width: r.width,
      height: r.height,
      bottom: r.bottom,
    };
  });
  const round = (value: number) => Math.round(value * 100) / 100;
  return {
    x: round(rect.x),
    y: round(rect.y),
    width: round(rect.width),
    height: round(rect.height),
    bottom: round(rect.bottom),
  };
}
