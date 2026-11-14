// Tests read the repository's files through tests/helpers/source-files.ts (readSource, readRepoFile,
// readText, sourceFiles, ...), so the path base and the directory walk exist once. A test that calls the
// file-system readers itself fails here. tests/helpers is where the readers live; tests/e2e and tests/ux
// run in Playwright and read their own fixtures and built output, each with its reason stated in the file.
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  frontendDir,
  readText,
  sourceFiles,
} from "@tests/helpers/source-files";

const testsDir = path.join(frontendDir, "tests");
const exemptDirs = ["e2e", "ux", "helpers"];
const directRead = /\b(?:readFileSync|readFile|readdirSync|readdir)\b/;
// A read of a .css file through the shared helper, or the helper that reads stylesheets as text.
const readsStylesheet =
  /\b(?:readSource|readFrontendFile|readRepoFile|readText)\(\s*["'`][^"'`]*\.css["'`]|helpers\/css-contract/;

describe("tests read source files through the shared helper", () => {
  it("no unit test calls a file-system reader directly", () => {
    const own = import.meta.filename;
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

  it("only the CSS policy tests read stylesheets: how a view looks is measured in the browser, not read from the CSS", () => {
    const policies = new Set([
      "css-policy.test.ts",
      "css-prefix-policy.test.ts",
    ]);
    const own = import.meta.filename;
    const files = sourceFiles(testsDir, /\.(?:ts|tsx)$/, [
      "node_modules",
      ...exemptDirs,
    ]).filter((file) => file !== own && !policies.has(path.basename(file)));
    const offenders = files
      .filter((file) => readsStylesheet.test(readText(file)))
      .map((file) => path.relative(testsDir, file));
    expect(
      offenders,
      `Measure it in tests/e2e (computed style, boxes) instead of reading the CSS: ${offenders.join(", ")}`,
    ).toEqual([]);
  });

  it("the stylesheet pattern finds a read of a .css file or the css-contract helper, and not a comment about one", () => {
    expect(readsStylesheet.test('readSource("features/x/y.css")')).toBe(true);
    expect(readsStylesheet.test("readRepoFile(`a/b.css`)")).toBe(true);
    expect(
      readsStylesheet.test(
        'import { readCss } from "@tests/helpers/css-contract";',
      ),
    ).toBe(true);
    expect(readsStylesheet.test("// the rule is in journal.css")).toBe(false);
  });

  it("the pattern finds the readers by name only", () => {
    expect(directRead.test('readFileSync(file, "utf8")')).toBe(true);
    expect(directRead.test("readdirSync(dir)")).toBe(true);
    expect(directRead.test("readSource(path)")).toBe(false);
    expect(directRead.test("readTextBack(x)")).toBe(false);
  });
});
