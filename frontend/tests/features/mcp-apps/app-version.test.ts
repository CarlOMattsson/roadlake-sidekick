import { expect, test } from "vitest";
import { APP_VERSION } from "@/features/mcp-apps/app-version";
import { readFrontendFile } from "@tests/helpers/source-files";

// The MCP App announces this in its host handshake. tools/check-version-sync.py keeps package.json equal to the release version.
test("the version the app announces is the version of package.json", () => {
  const raw = readFrontendFile("package.json");
  const manifest = JSON.parse(raw) as { version: string };
  expect(APP_VERSION).toBe(manifest.version);
  expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
});
