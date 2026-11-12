import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, mergeConfig } from "vitest/config";

import baseConfig from "./vite.config";
import { PREACT_COMPAT_ALIASES } from "./vite.mcp-app-alias";

/**
 * Test files that pass on React but fail on Preact's compat layer (focus after a re-render, event batching, an input
 * that stays mounted). Each one is a Preact difference in the shipped bundle or a test that depends on React timing,
 * to be settled one file at a time: fix it and delete the line. The list may only shrink; a new test file runs on
 * Preact from the start.
 */
const PREACT_DIFFERS = [
  "tests/agenda-queue.test.tsx",
  "tests/agenda-triage.test.tsx",
  "tests/agenda-view-text-size.test.tsx",
  "tests/board-kanban.test.tsx",
  "tests/board-queue.test.tsx",
  "tests/control-memory.test.tsx",
  "tests/create-field-promise.test.tsx",
  "tests/hierarchy-view.test.tsx",
  "tests/journal-entry-limits.test.tsx",
  "tests/mcp-license-signal.test.tsx",
  "tests/new-task-input.test.tsx",
  "tests/task-props-due-stockholm.test.tsx",
  "tests/task-quick-status.test.tsx",
  "tests/task-steps-manage.test.tsx",
  "tests/work-app-contact.test.tsx",
  "tests/work-app-contacts-list.test.tsx",
  "tests/work-app-project-links.test.tsx",
  "tests/work-app-task-edit.test.tsx",
];

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
      // Merged with the base config's excludes. The mobile shell renders with real React (vite.mobile.config.ts),
      // so Preact says nothing about its tests.
      exclude: ["tests/mobile-*.test.tsx", ...PREACT_DIFFERS],
    },
  }),
);
