// Tests read the repository's files through tests/helpers/source-files.ts (readSource, readRepoFile,
// readText, sourceFiles, ...), so the path base and the directory walk exist once. A test that calls the
// file-system readers itself fails here. tests/helpers is where the readers live; tests/e2e and tests/ux
// run in Playwright and read their own fixtures and built output, each with its reason stated in the file.
import path from "node:path";
import { describe, expect, it } from "vitest";

import { readText, sourceFiles } from "./helpers/source-files";

const testsDir = import.meta.dirname;
const exemptDirs = ["e2e", "ux", "helpers"];
const directRead = /\b(?:readFileSync|readFile|readdirSync|readdir)\b/;

describe("tests read source files through the shared helper", () => {
  it("no unit test calls a file-system reader directly", () => {
    const own = path.join(testsDir, path.basename(import.meta.filename));
    const files = sourceFiles(testsDir, /\.(?:ts|tsx)$/, [
      "node_modules",
      ...exemptDirs,
    ]).filter((file) => file !== own);
    expect(files.length).toBeGreaterThan(50);
    const offenders = files
      .filter((file) => directRead.test(readText(file)))
      .map((file) => path.relative(testsDir, file));
    expect(
      offenders,
      `Read through tests/helpers/source-files.ts instead: ${offenders.join(", ")}`,
    ).toEqual([]);
  });

  it("the pattern finds the readers by name only", () => {
    expect(directRead.test('readFileSync(file, "utf8")')).toBe(true);
    expect(directRead.test("readdirSync(dir)")).toBe(true);
    expect(directRead.test("readSource(path)")).toBe(false);
    expect(directRead.test("readTextBack(x)")).toBe(false);
  });
});
