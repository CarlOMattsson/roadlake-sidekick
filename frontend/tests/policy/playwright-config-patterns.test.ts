// Every testMatch/testIgnore pattern of the Playwright configs must hit at least one file under its testDir.
// A pattern for a file that is missing (or not shipped) otherwise passes silently:
// Playwright just runs fewer specs. Configs that are not in this checkout are skipped.
import path from "node:path";
// Every config imports Playwright's runtime, a large package whose first load took over 15 s on a busy machine and
// timed out the first config's test. Loading it here keeps that cost in file collection, which has no timeout.
import "@playwright/test";
import { describe, expect, it } from "vitest";

import {
  entryNames,
  frontendDir as root,
  sourceFiles,
} from "@tests/helpers/source-files";

const configNames = entryNames(root, /^playwright\..*\.config\.ts$/);

type Pattern = string | RegExp;
type Scope = {
  testDir?: string;
  testMatch?: Pattern | Pattern[];
  testIgnore?: Pattern | Pattern[];
};
type Config = Scope & { projects?: Scope[] };

function asList(value: Pattern | Pattern[] | undefined): Pattern[] {
  return value === undefined ? [] : Array.isArray(value) ? value : [value];
}

describe("Playwright config patterns", () => {
  it("finds the configs", () => {
    expect(configNames).toContain("playwright.mobile-audit.config.ts");
  });

  for (const name of configNames) {
    it(`${name}: every testMatch/testIgnore pattern matches a file`, async () => {
      const module = (await import(
        /* @vite-ignore */ path.join(root, name)
      )) as {
        default: Config;
      };
      const config = module.default;
      const scopes: Scope[] = [config, ...(config.projects ?? [])];
      const misses: string[] = [];
      for (const scope of scopes) {
        const dir = path.resolve(root, scope.testDir ?? config.testDir ?? ".");
        const files = sourceFiles(dir).map((file) =>
          path.relative(dir, file).split(path.sep).join("/"),
        );
        for (const kind of ["testMatch", "testIgnore"] as const) {
          for (const pattern of asList(scope[kind])) {
            const hit =
              typeof pattern === "string"
                ? files.includes(pattern.replace(/^\.\//, ""))
                : files.some((file) => pattern.test(file));
            if (!hit)
              misses.push(
                `${kind} ${String(pattern)} in ${path.relative(root, dir)}`,
              );
          }
        }
      }
      expect(misses).toEqual([]);
    });
  }
});
