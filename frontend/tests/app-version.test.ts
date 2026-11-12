import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import { APP_VERSION } from "@/features/mcp-apps/app-version";

// The MCP App announces this in its host handshake. tools/check-version-sync.py keeps package.json equal to the release version.
test("the version the app announces is the version of package.json", () => {
  const raw = readFileSync(
    path.resolve(import.meta.dirname, "../package.json"),
    "utf8",
  );
  const manifest = JSON.parse(raw) as { version: string };
  expect(APP_VERSION).toBe(manifest.version);
  expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
});
