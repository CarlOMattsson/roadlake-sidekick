// CSS prefix policy: Sidekick's own class names, container names, keyframes and custom properties
// start with sk- / --sk-. The prefix ch- / --ch- must not come
// back, neither in the source nor in the built CSS the MCP App serves.
//
// The prefix counts only where it starts a name: "search-", "match-", "touch-", "each-" or
// "--branch-" never match, because the character before "ch-" is part of the same word.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { sourceFiles } from "./helpers/source-files";

const frontendDir = path.resolve(import.meta.dirname, "..");
const repoDir = path.resolve(frontendDir, "..");

const legacyPrefix = /(?<![A-Za-z0-9_$-])(?:--)?ch-/g;

const sourceExtensions = new Set([".ts", ".tsx", ".css", ".html", ".json"]);

function legacyHits(files: string[]): string[] {
  return files.flatMap((file) => {
    const text = readFileSync(file, "utf8");
    return [...text.matchAll(legacyPrefix)].map((match) => {
      const line = text.slice(0, match.index).split("\n").length;
      const excerpt = text.slice(match.index, match.index + 40).split(/\s/)[0];
      return `${path.relative(repoDir, file)}:${line}: ${excerpt}`;
    });
  });
}

describe("CSS prefix policy (sk-, never ch-)", () => {
  it("frontend/src uses no ch- or --ch- prefix", () => {
    const files = sourceFiles(path.join(frontendDir, "src"), (name) =>
      sourceExtensions.has(path.extname(name)),
    );
    expect(files.length).toBeGreaterThan(0);
    expect(legacyHits(files)).toEqual([]);
  });

  it("the built MCP App and mobile CSS use no ch- or --ch- prefix", () => {
    // The committed single-file MCP App (CSS inlined) is always there; the dist folders exist
    // after `npm run build:mcp-app` / `npm run build:mobile` and are checked when present.
    const committedApp = path.join(
      repoDir,
      "backend/src/sidekick/mcp/apps/sidekick.html",
    );
    const built = [
      ...(existsSync(committedApp) ? [committedApp] : []),
      ...sourceFiles(path.join(frontendDir, "dist-mcp-app"), /\.css$/),
      ...sourceFiles(path.join(frontendDir, "dist-mobile"), /\.css$/),
    ];
    expect(built.length).toBeGreaterThan(0);
    expect(legacyHits(built)).toEqual([]);
  });

  it("the pattern matches only a prefix that starts a name", () => {
    const sample =
      ".ch-card var(--ch-fg) search-box match-row touch-action each-item --branch-x";
    expect(sample.match(legacyPrefix)).toEqual(["ch-", "--ch-"]);
  });
});
