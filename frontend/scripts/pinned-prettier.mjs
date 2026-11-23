// Loads the prettier that frontend/ pins, for the generators that write formatted files
// (generate-tool-types.mjs, tool-shapes.mjs).
//
// Generated files are committed and compared byte for byte, so they must be formatted by the
// repo's own prettier. A bare `import "prettier"` resolves from wherever Node finds one, which in a
// git worktree without frontend/node_modules can be nothing, or a different copy found further up
// the directory tree. This loader resolves only from frontend/ and throws a clear error when
// prettier is not installed there, so a generator never writes unformatted or differently
// formatted output.
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const INSTALL_HINT = "Run: npm --prefix frontend ci";

/** The prettier version frontend/package.json pins, or null when it pins none. */
export function pinnedPrettierVersion() {
  const manifest = JSON.parse(
    readFileSync(resolve(frontendDir, "package.json"), "utf8"),
  );
  return (
    manifest.devDependencies?.prettier ??
    manifest.dependencies?.prettier ??
    null
  );
}

/**
 * Loads the prettier installed in frontend/node_modules.
 * Throws when it is missing, resolves to a copy outside frontend/node_modules, or is not the pinned version.
 * @returns {{ prettier: typeof import("prettier"), version: string, pinned: string | null }}
 */
export function loadPinnedPrettier() {
  const require = createRequire(resolve(frontendDir, "package.json"));
  // Real paths on both sides: frontend/node_modules may be a symlink (a worktree sharing one install).
  const installedLink = resolve(frontendDir, "node_modules", "prettier");
  const installedRoot = existsSync(installedLink)
    ? realpathSync(installedLink)
    : installedLink;
  let entry;
  try {
    entry = require.resolve("prettier");
  } catch (error) {
    throw new Error(
      `prettier cannot be resolved from ${frontendDir}, so the generated file would be left unformatted. ${INSTALL_HINT}`,
      { cause: error },
    );
  }
  if (!realpathSync(entry).startsWith(installedRoot + sep)) {
    throw new Error(
      `prettier resolved to ${entry}, outside ${installedRoot}. Refusing to format with a copy other than the one frontend/ pins. ${INSTALL_HINT}`,
    );
  }
  const { version } = JSON.parse(
    readFileSync(resolve(installedRoot, "package.json"), "utf8"),
  );
  const pinned = pinnedPrettierVersion();
  if (pinned && version !== pinned) {
    throw new Error(
      `frontend/node_modules has prettier ${version} but package.json pins ${pinned}; it formats generated files differently. ${INSTALL_HINT}`,
    );
  }
  return { prettier: require("prettier"), version, pinned };
}

/**
 * Formats TypeScript source with the pinned prettier and the config found from `configPath`.
 * @param {string} source
 * @param {string} configPath a path inside frontend/, to resolve its prettier config from
 */
export async function formatTypeScript(source, configPath) {
  const { prettier } = loadPinnedPrettier();
  const config = (await prettier.resolveConfig(configPath)) ?? {};
  return prettier.format(source, { ...config, parser: "typescript" });
}
