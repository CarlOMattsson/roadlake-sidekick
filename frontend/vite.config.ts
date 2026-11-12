import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  // This config is Vitest's only (the MCP App and the mobile shell have their own).
  test: {
    environment: "jsdom",
    setupFiles: "./tests/setup.ts",
    exclude: [
      "tests/e2e/**",
      // Screenshot scripts: run by hand with Playwright, never by vitest.
      "tests/ux/**",
      "node_modules/**",
      "dist/**",
    ],
    /*
     * Vitest's default is 5s, which is too tight for this suite.
     *
     * Most tests render a whole room (the MCP App views and the mobile shell, with their providers and
     * transport fakes) and drive it through `userEvent`. A single test takes one to three seconds in jsdom on an
     * idle machine and longer on a loaded machine or a shared CI runner, where it would
     * otherwise fail as a timeout while the assertions are correct.
     *
     * The ceiling does not slow a passing run down: it only decides how long a test may take
     * before it counts as failed. A test that genuinely hangs still fails.
     */
    testTimeout: 30_000,
    hookTimeout: 30_000,
    coverage: {
      provider: "v8",
      thresholds: {
        lines: 91,
      },
    },
  },
});
