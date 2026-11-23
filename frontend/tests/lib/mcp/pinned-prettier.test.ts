import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  loadPinnedPrettier,
  pinnedPrettierVersion,
} from "../../../scripts/pinned-prettier.mjs";

const scriptsDir = join(__dirname, "../../../scripts");
const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true });
});

describe("pinned prettier loader", () => {
  it("loads the prettier installed in frontend/node_modules", () => {
    const { prettier, version } = loadPinnedPrettier();
    expect(typeof prettier.format).toBe("function");
    expect(version).toMatch(/^\d+\.\d+\.\d+/);
    expect(pinnedPrettierVersion()).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("fails with a clear message when prettier cannot be resolved", () => {
    // A frontend/ copy with no node_modules anywhere above it, as in a fresh git worktree.
    const root = mkdtempSync(join(tmpdir(), "pinned-prettier-"));
    roots.push(root);
    mkdirSync(join(root, "scripts"));
    copyFileSync(
      join(scriptsDir, "pinned-prettier.mjs"),
      join(root, "scripts/pinned-prettier.mjs"),
    );
    writeFileSync(
      join(root, "package.json"),
      JSON.stringify({ devDependencies: { prettier: "3.10.1" } }),
    );
    const run = () =>
      execFileSync(
        process.execPath,
        [
          "--input-type=module",
          "-e",
          'import { loadPinnedPrettier } from "./scripts/pinned-prettier.mjs"; loadPinnedPrettier();',
        ],
        { cwd: root, stdio: "pipe" },
      );
    expect(run).toThrow(/prettier cannot be resolved/);
    expect(run).toThrow(/npm --prefix frontend ci/);
  });
});
