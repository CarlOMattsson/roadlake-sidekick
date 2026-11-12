import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, mergeConfig } from "vitest/config";

import baseConfig from "./vite.config";
import { PREACT_COMPAT_ALIASES } from "./vite.mcp-app-alias";

/**
 * Runs a representative sample of the MCP App view tests against Preact's compat layer, with the same aliases
 * as the shipped bundle (vite.mcp-app.config.ts). The default Vitest run uses React, so Preact-only differences
 * (native events, batched updates) would otherwise surface only in Playwright. Run: `npm run test:mcp-app:preact`.
 */
export default mergeConfig(
  baseConfig,
  defineConfig({
    plugins: [react()],
    resolve: {
      alias: [
        { find: "@", replacement: path.resolve(import.meta.dirname, "src") },
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
      include: [
        "tests/mcp-sidekick-shell.test.tsx",
        "tests/mcp-sidekick-rooms.test.tsx",
        "tests/mcp-unsaved-guard.test.tsx",
        "tests/mcp-enabled-rooms.test.tsx",
        "tests/mcp-sidekick-refresh-in-place.test.tsx",
      ],
    },
  }),
);
