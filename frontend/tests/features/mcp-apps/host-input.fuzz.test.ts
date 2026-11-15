// Property-based fuzzing of what the app reads from the host: the ui/initialize answer, tool results routed to a
// room, links the app asks the host to open and the host's CSS variables. Everything here is untrusted input.
import fc from "fast-check";
import { describe, expect, it } from "vitest";

import {
  featuresFrom,
  isAllowedLinkUrl,
  isSupportedProtocolVersion,
  MIN_SUPPORTED_PROTOCOL,
} from "@/features/mcp-apps/bridge";
import { applyHostStyle } from "@/features/mcp-apps/host-style";
import {
  isRoomId,
  routeFor,
  routeForTool,
  TOOL_ROUTES,
} from "@/features/mcp-apps/router";

/** Any JSON-like value, nested, including the keys the router and the bridge look at. */
const hostValue = fc.letrec((tie) => ({
  value: fc.oneof(
    { depthSize: "small" },
    fc.anything(),
    fc.array(tie("value"), { maxLength: 4 }),
    fc.dictionary(
      fc.oneof(
        fc.constantFrom(
          "card",
          "kind",
          "task",
          "id",
          "contact",
          "projects",
          "tasks",
          "items",
          "item",
          "contacts",
          "journal_date",
          "entries",
          "summary",
          "has_more",
          "next_cursor",
          "filters",
          "__proto__",
          "constructor",
        ),
        fc.string(),
      ),
      tie("value"),
      { maxKeys: 6 },
    ),
  ),
})).value;

describe("routing a host tool result (fuzzed)", () => {
  it("never throws and only ever names a known room", () => {
    fc.assert(
      fc.property(
        fc.oneof(fc.constantFrom(...Object.keys(TOOL_ROUTES)), hostValue),
        hostValue,
        fc.boolean(),
        (toolName, structuredContent, isError) => {
          const route = routeFor({ toolName, structuredContent, isError });
          if (route !== undefined) {
            expect(isRoomId(route.room)).toBe(true);
            expect(typeof route.view).toBe("string");
          }
        },
      ),
      { numRuns: 1000 },
    );
  });

  it("reads a namespaced tool name as its last segment, and nothing else as a tool", () => {
    const tool = fc.constantFrom(...Object.keys(TOOL_ROUTES));
    const separator = fc.constantFrom("__", ":", "/", ".");
    fc.assert(
      fc.property(fc.string(), separator, tool, (prefix, sep, name) => {
        expect(routeForTool(`${prefix}${sep}${name}`)).toBe(TOOL_ROUTES[name]);
      }),
    );
    fc.assert(
      fc.property(fc.string(), (name) => {
        const route = routeForTool(name);
        if (route !== undefined)
          expect(Object.values(TOOL_ROUTES)).toContain(route);
      }),
      { numRuns: 1000 },
    );
  });
});

describe("the ui/initialize answer (fuzzed)", () => {
  it("reads capabilities as three booleans from any value", () => {
    fc.assert(
      fc.property(hostValue, (capabilities) => {
        const features = featuresFrom(capabilities);
        expect(Object.keys(features).sort()).toEqual([
          "message",
          "openLinks",
          "serverTools",
        ]);
        for (const flag of Object.values(features))
          expect(typeof flag).toBe("boolean");
      }),
    );
  });

  it("accepts a protocol version only as an ISO date no older than the minimum", () => {
    fc.assert(
      fc.property(
        fc.oneof(
          hostValue,
          fc
            .date({ noInvalidDate: true })
            .map((d) => d.toISOString().slice(0, 10)),
        ),
        (version) => {
          if (isSupportedProtocolVersion(version)) {
            expect(version).toMatch(/^\d{4}-\d{2}-\d{2}$/);
            expect(
              typeof version === "string" && version >= MIN_SUPPORTED_PROTOCOL,
            ).toBe(true);
          }
        },
      ),
      { numRuns: 500 },
    );
  });
});

describe("links the app passes to the host (fuzzed)", () => {
  // Text a browser's URL parser drops or folds before it reads the scheme.
  const tricky = fc.constantFrom(
    " ",
    "\t",
    "\n",
    "\u0000",
    " ",
    "﻿",
    " ",
    "%0a",
    "&#58;",
    ":",
    "/",
    "\\",
  );
  const schemeLike = fc.constantFrom(
    "https:",
    "HTTPS:",
    "mailto:",
    "tel:",
    "http:",
    "javascript:",
    "JaVaScRiPt:",
    "data:",
    "vbscript:",
    "blob:",
    "file:",
  );
  const link = fc
    .array(fc.oneof(tricky, schemeLike, fc.string({ maxLength: 8 })), {
      maxLength: 8,
    })
    .map((parts) => parts.join(""));

  it("an accepted link always resolves to mailto:, tel: or https:", () => {
    fc.assert(
      fc.property(link, (url) => {
        if (!isAllowedLinkUrl(url)) return;
        let protocol: string;
        try {
          protocol = new URL(url.trim(), "https://app.invalid/").protocol;
        } catch {
          return; // Not a URL at all: the host and the anchor open nothing.
        }
        expect(["https:", "mailto:", "tel:"]).toContain(protocol);
      }),
      { numRuns: 2000 },
    );
  });
});

/** The value a CSS parser reads: hex escapes (`\75 `) and character escapes (`\u`) resolved. */
function cssUnescaped(value: string): string {
  return value.replace(
    /\\(?:([0-9a-f]{1,6})[ \t\n\r\f]?|([\s\S]))/gi,
    (_, hex: string | undefined, char: string | undefined) =>
      hex === undefined
        ? (char ?? "")
        : String.fromCodePoint(Math.min(parseInt(hex, 16), 0x10ffff) || 0xfffd),
  );
}

/** Values a CSS parser would load a resource from or that would end the declaration. */
const LOADS_OR_ESCAPES =
  /(?:url|src|image|image-set|cross-fade|element)\(|@import|;/i;

describe("host CSS variables (fuzzed)", () => {
  /** A loader function with some letters written as CSS escapes: `\75 rl(`, `u\r\6c(`. */
  const escapedLoader = fc
    .constantFrom("url(", "src(", "image-set(", "@import")
    .chain((word) =>
      fc
        .array(fc.constantFrom("plain", "hex", "char"), {
          minLength: word.length,
          maxLength: word.length,
        })
        .map((styles) =>
          Array.from(word, (letter, i) =>
            /[a-z]/.test(letter) && styles[i] === "hex"
              ? `\\${letter.charCodeAt(0).toString(16)} `
              : /[a-z]/.test(letter) && styles[i] === "char"
                ? `\\${letter}`
                : letter,
          ).join(""),
        ),
    );
  const fragment = fc.oneof(
    escapedLoader,
    fc.constantFrom(
      "url(",
      "URL(",
      "u",
      "r",
      "l",
      "(",
      ")",
      "\\",
      "\\75 ",
      "\\55",
      "\\72 ",
      "\\6c ",
      "\\l",
      "@",
      "import",
      "@import",
      ";",
      "image-set(",
      "src(",
      '"',
      " ",
      "#fff",
      "https://example.invalid/a.png",
    ),
    fc.string({ maxLength: 6 }),
  );
  const value = fc
    .array(fragment, { maxLength: 8 })
    .map((parts) => parts.join(""));
  const name = fc.oneof(
    fc.constantFrom("--color-text-primary", "--font-text-body", "color", "--"),
    fc.string({ maxLength: 12 }).map((text) => `--${text}`),
  );

  it("sets only well-named variables whose value cannot load anything", () => {
    fc.assert(
      fc.property(
        fc.dictionary(name, fc.oneof(value, hostValue), { maxKeys: 4 }),
        (variables) => {
          const root = document.createElement("div");
          applyHostStyle({ styles: { variables } }, root);
          for (let i = 0; i < root.style.length; i += 1) {
            const property = root.style.item(i);
            if (property.startsWith("--host-safe-")) continue;
            expect(property).toMatch(/^--[a-z0-9-]{1,64}$/);
            const applied = root.style.getPropertyValue(property);
            expect(cssUnescaped(applied)).not.toMatch(LOADS_OR_ESCAPES);
          }
        },
      ),
      { numRuns: 2000 },
    );
  });
});
