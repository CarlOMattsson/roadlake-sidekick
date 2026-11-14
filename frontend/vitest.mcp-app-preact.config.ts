import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, mergeConfig } from "vitest/config";

import baseConfig from "./vite.config";
import { PREACT_COMPAT_ALIASES } from "./vite.mcp-app-alias";

/**
 * Runs every MCP App view test against Preact's compat layer, with the same aliases as the shipped bundle
 * (vite.mcp-app.config.ts). The default Vitest run uses React, so Preact-only differences (native events, batched
 * updates) would otherwise surface only in Playwright. Run: `npm run test:mcp-app:preact`; `npm run check` runs it too.
 */
export default mergeConfig(
  baseConfig,
  defineConfig({
    plugins: [react()],
    resolve: {
      alias: [
        { find: "@", replacement: path.resolve(import.meta.dirname, "src") },
        {
          find: "@tests",
          replacement: path.resolve(import.meta.dirname, "tests"),
        },
        // Testing Library's React package would render with React, so the Preact run uses a thin stand-in.
        {
          find: /^@testing-library\/react$/,
          replacement: path.resolve(
            import.meta.dirname,
            "tests/preact/testing-library-react.ts",
          ),
        },
        ...PREACT_COMPAT_ALIASES,
        // Vitest compiles JSX for development; the production bundle only needs the jsx-runtime alias above.
        { find: /^react\/jsx-dev-runtime$/, replacement: "preact/jsx-runtime" },
      ],
    },
    test: {
      include: ["tests/**/*.test.tsx"],
      // Added to the base config's setup file: it makes Preact's after-paint effects safe at jsdom teardown.
      setupFiles: ["./tests/preact/setup.ts"],
      // Merged with the base config's excludes. The mobile shell renders with real React (vite.mobile.config.ts),
      // so Preact says nothing about its tests.
      exclude: ["tests/mobile/**"],
    },
  }),
);
