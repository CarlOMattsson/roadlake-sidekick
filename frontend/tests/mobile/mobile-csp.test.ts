// The Android app's page (mobile.html) must carry a strict Content-Security-Policy that matches what it loads:
// its own bundle only, no network call from the page (the companion server is reached through the native
// SidekickNative plugin), no inline script or style, no eval. The source page is always checked; the built page
// (dist-mobile/index.html, from `npm run build:mobile`) is checked as well when it exists, because the build is what
// the app packages and must not add an inline script or style the policy would block. In a CI run (CI is set) the
// built page is required: CI builds it before the unit tests, and a missing artifact fails here instead of
// skipping the check unseen. Locally it is still skipped until `npm run build:mobile` has run.
import path from "node:path";
import { describe, expect, it } from "vitest";

import { fileExists, frontendDir, readText } from "@tests/helpers/source-files";

const buildRequired = Boolean(process.env.CI);
const pages = {
  "mobile.html": path.join(frontendDir, "mobile.html"),
  "dist-mobile/index.html": path.join(frontendDir, "dist-mobile", "index.html"),
};

function policyOf(html: string): Map<string, string[]> {
  const meta = html.match(
    /<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"/,
  );
  expect(meta, "no Content-Security-Policy meta tag").not.toBeNull();
  const directives = new Map<string, string[]>();
  for (const part of (meta?.[1] ?? "").split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/);
    if (name) directives.set(name, sources);
  }
  return directives;
}

for (const [label, file] of Object.entries(pages)) {
  if (buildRequired && !fileExists(file)) {
    describe(`the CSP of ${label}`, () => {
      it("exists (run `npm run build:mobile` before the tests)", () => {
        expect(fileExists(file), `${label} is missing`).toBe(true);
      });
    });
    continue;
  }
  describe.skipIf(!fileExists(file))(`the CSP of ${label}`, () => {
    const html = (): string => readText(file);

    it("is present, starts from default-src 'none' and allows no eval or inline code", () => {
      const policy = policyOf(html());
      expect(policy.get("default-src")).toEqual(["'none'"]);
      const text = [...policy.values()].flat().join(" ");
      expect(text).not.toContain("unsafe-eval");
      expect(text).not.toContain("unsafe-inline");
      expect(text).not.toContain("wasm-unsafe-eval");
      expect(text).not.toContain("*");
    });

    it("lets the page load only its own bundle and make no network call of its own", () => {
      const policy = policyOf(html());
      expect(policy.get("script-src")).toEqual(["'self'"]);
      expect(policy.get("style-src")).toEqual(["'self'"]);
      expect(policy.get("connect-src")).toEqual(["'none'"]);
      expect(policy.get("object-src")).toEqual(["'none'"]);
      expect(policy.get("base-uri")).toEqual(["'none'"]);
      expect(policy.get("form-action")).toEqual(["'none'"]);
      const origins = [...policy.values()]
        .flat()
        .filter((source) => /^[a-z][a-z0-9+.-]*:\/\//i.test(source));
      expect(origins).toEqual([]);
    });

    it("has no inline script, inline style or style attribute the policy would block", () => {
      // Comments are not content; strip them so the CSP note in the source page does not count.
      const markup = html().replace(/<!--[\s\S]*?-->/g, "");
      expect(markup).not.toMatch(/<style[\s>]/i);
      expect(markup).not.toMatch(/<script(?![^>]*\ssrc=)[^>]*>/i);
      expect(markup).not.toMatch(/\sstyle\s*=/i);
      expect(markup).not.toMatch(/\son[a-z]+\s*=/i);
    });
  });
}
