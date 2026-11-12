/**
 * Shared reading of the app's own source and stylesheets for tests.
 *
 * Contract tests that scan source text on purpose (no forbidden API, CSS prefixes, no Swedish comments) and
 * tests that check a stylesheet against rendered markup both read files through here, so the path base and the
 * directory walk exist once.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

/** `frontend/src`. */
export const srcDir = path.resolve(import.meta.dirname, "../../src");

/** The repository root, for the few contract tests that read a file outside `frontend`. */
export const repoDir = path.resolve(import.meta.dirname, "../../..");

/** The text of `relativePath` taken from the repository root. */
export function readRepoFile(relativePath: string): string {
  return readFileSync(path.join(repoDir, relativePath), "utf8");
}

/** The source text of `relativePath`, taken from `frontend/src`. */
export function readSource(relativePath: string): string {
  return readFileSync(path.join(srcDir, relativePath), "utf8");
}

/**
 * Every file under `directory` whose name matches `include` (a pattern, or a predicate on the file name; every
 * file by default), as absolute paths, sorted. `skip` names directories that are not walked. A directory that
 * does not exist holds no files (a build output that has not been built).
 */
export function sourceFiles(
  directory: string = srcDir,
  include: RegExp | ((name: string) => boolean) = () => true,
  skip: readonly string[] = ["node_modules"],
): string[] {
  if (!existsSync(directory)) return [];
  const wanted = (name: string) =>
    typeof include === "function" ? include(name) : include.test(name);
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        return skip.includes(entry.name)
          ? []
          : sourceFiles(full, include, skip);
      }
      return wanted(entry.name) ? [full] : [];
    })
    .sort();
}
