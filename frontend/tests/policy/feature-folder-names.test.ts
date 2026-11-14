import { describe, expect, it } from "vitest";

import { directoryNames, featuresDir } from "@tests/helpers/source-files";

// Every MCP app lives in `src/features/<name>-app`. The only other folder is the shared
// host shell `mcp-apps`, which the apps mount into.
const SHARED_FOLDERS = new Set(["mcp-apps"]);

describe("src/features folder names", () => {
  it("names every app folder with the -app suffix", () => {
    const folders = directoryNames(featuresDir);

    const offenders = folders.filter(
      (name) => !SHARED_FOLDERS.has(name) && !name.endsWith("-app"),
    );

    expect(folders).toContain("shopping-app");
    expect(offenders).toEqual([]);
  });
});
