/**
 * Shared reading of the app's own source and stylesheets for tests.
 *
 * Contract tests that scan source text on purpose (no forbidden API, CSS prefixes, no Swedish comments) and
 * tests that check a stylesheet against rendered markup both read files through here, so the path base and the
 * directory walk exist once.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

/** `frontend`. */
export const frontendDir = path.resolve(import.meta.dirname, "../..");

/** `frontend/src`. */
export const srcDir = path.join(frontendDir, "src");

/** `frontend/src/features`. */
export const featuresDir = path.join(srcDir, "features");

/** The repository root, for the few contract tests that read a file outside `frontend`. */
export const repoDir = path.resolve(frontendDir, "..");

/** The text of the file at `absolutePath`, such as one found by `sourceFiles` or named by a script. */
export function readText(absolutePath: string): string {
  return readFileSync(absolutePath, "utf8");
}

/** The text of `relativePath` taken from `frontend`. */
export function readFrontendFile(relativePath: string): string {
  return readText(path.join(frontendDir, relativePath));
}

/** Whether `absolutePath` exists, for build output that may not have been built. */
export function fileExists(absolutePath: string): boolean {
  return existsSync(absolutePath);
}

/** The names of the entries of `directory` that are directories, sorted. */
export function directoryNames(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

/** The names of the entries directly in `directory` that match `include`, sorted. */
export function entryNames(directory: string, include: RegExp): string[] {
  return readdirSync(directory)
    .filter((name) => include.test(name))
    .sort();
}

/** The text of `relativePath` taken from the repository root. */
export function readRepoFile(relativePath: string): string {
  return readText(path.join(repoDir, relativePath));
}

/** The source text of `relativePath`, taken from `frontend/src`. */
export function readSource(relativePath: string): string {
  return readText(path.join(srcDir, relativePath));
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
