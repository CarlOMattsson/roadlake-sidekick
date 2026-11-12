/**
 * The React-to-Preact aliases of the MCP App bundle. The bundle build (vite.mcp-app.config.ts) and the Vitest
 * project that mirrors it (vitest.mcp-app-preact.config.ts) both import this list, so they cannot drift apart.
 */
export const PREACT_COMPAT_ALIASES = [
  { find: /^react$/, replacement: "preact/compat" },
  { find: /^react-dom$/, replacement: "preact/compat" },
  { find: /^react-dom\/client$/, replacement: "preact/compat/client" },
  { find: /^react\/jsx-runtime$/, replacement: "preact/jsx-runtime" },
];
