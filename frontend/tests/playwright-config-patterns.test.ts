// Every testMatch/testIgnore pattern of the Playwright configs must hit at least one file under its testDir.
// A pattern for a file that is missing (or not shipped) otherwise passes silently:
// Playwright just runs fewer specs. Configs that are not in this checkout are skipped.
import { existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(import.meta.dirname, "..");

const configNames = readdirSync(root).filter((name) =>
  /^playwright\..*\.config\.ts$/.test(name),
);

type Pattern = string | RegExp;
type Scope = {
  testDir?: string;
  testMatch?: Pattern | Pattern[];
  testIgnore?: Pattern | Pattern[];
};
type Config = Scope & { projects?: Scope[] };

function filesUnder(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (entry === "node_modules") return [];
    return statSync(full).isDirectory() ? filesUnder(full) : [full];
  });
}

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
        const files = filesUnder(dir).map((file) =>
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
