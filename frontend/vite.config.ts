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
     * Vitest's default is 5s, which is too tight for this suite: most tests render a whole room (the MCP App views
     * and the mobile shell, with their providers and transport fakes) and drive it through `userEvent`, and the
     * slowest take five to nine seconds in a full run on a busy machine. Fifteen seconds leaves headroom over
     * that without letting a hung test hold a run for half a minute. The ceiling does not slow a passing run down.
     */
    testTimeout: 15_000,
    hookTimeout: 15_000,
    coverage: {
      provider: "v8",
      thresholds: {
        lines: 91,
      },
    },
  },
});
