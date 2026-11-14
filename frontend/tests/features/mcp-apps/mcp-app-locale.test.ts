import { describe, expect, it } from "vitest";
import { appLocale, applyAppLocale } from "@/features/mcp-apps/app-locale";

// The Sidekick setting SIDEKICK_MCP_APP_LOCALE arrives as a meta tag in the app document. The host's
// locale is not an input to appLocale at all, so an en-US host cannot change the language.
function documentWith(head: string, body = ""): Document {
  const doc = document.implementation.createHTMLDocument("app");
  doc.head.innerHTML = head;
  doc.body.innerHTML = body;
  return doc;
}

describe("Sidekick MCP App locale", () => {
  it("is Swedish when the Sidekick setting is not declared, whatever the host locale", () => {
    expect(appLocale(documentWith(""))).toBe("sv");
  });

  it("is English when the Sidekick setting is en", () => {
    const doc = documentWith('<meta name="sidekick-app-locale" content="en">');
    expect(appLocale(doc)).toBe("en");
  });

  it("is Swedish when the Sidekick setting is sv", () => {
    const doc = documentWith('<meta name="sidekick-app-locale" content="sv">');
    expect(appLocale(doc)).toBe("sv");
  });

  it("falls back to Swedish for an unknown value", () => {
    const doc = documentWith('<meta name="sidekick-app-locale" content="de">');
    expect(appLocale(doc)).toBe("sv");
  });

  it("sets lang on the app root element", () => {
    const doc = documentWith("", '<div id="root"></div>');
    applyAppLocale("en", doc);
    expect(doc.getElementById("root")?.getAttribute("lang")).toBe("en");
    applyAppLocale("sv", doc);
    expect(doc.getElementById("root")?.getAttribute("lang")).toBe("sv");
  });

  it("sets lang on the document element, so the page language is never empty", () => {
    const doc = documentWith("", '<div id="root"></div>');
    applyAppLocale("en", doc);
    expect(doc.documentElement.lang).toBe("en");
    applyAppLocale("sv", doc);
    expect(doc.documentElement.lang).toBe("sv");
  });
});
