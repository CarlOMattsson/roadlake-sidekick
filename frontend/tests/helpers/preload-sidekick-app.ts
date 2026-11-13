/**
 * Loads the module graph the Sidekick MCP App entry builds on (the shell and the four rooms), without running the
 * entry. Test files that import `sidekick-entry` in `beforeAll` (it reads its locale and binds the bridge at import
 * time, so it cannot be imported earlier) await this at the top level: loading a few hundred modules is the one
 * expensive step, and on a busy machine it ran past the hook timeout. At the top level it belongs to file
 * collection, which has no timeout, and the entry import left in `beforeAll` only runs the entry's own code.
 * Nothing in these modules reads the locale or the bridge when it is imported; the rooms do that at render time.
 */
export async function preloadSidekickApp(): Promise<void> {
  await Promise.all([
    import("@/features/mcp-apps/sidekick-shell"),
    import("@/features/mcp-apps/sidekick-rooms"),
  ]);
}
