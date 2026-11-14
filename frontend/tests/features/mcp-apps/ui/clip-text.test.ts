import { describe, expect, it } from "vitest";

import { clipAtWord } from "@/features/mcp-apps/ui/clip-text";

/** A room of `n` characters. */
const room = (n: number) => (candidate: string) => candidate.length <= n;

describe("clipAtWord", () => {
  it("returns the text whole when it fits", () => {
    expect(clipAtWord("Kort text.", room(20))).toBe("Kort text.");
  });

  it("cuts after a whole word and adds the ellipsis", () => {
    expect(clipAtWord("Kunden vill ha offerten före fredag", room(24))).toBe(
      "Kunden vill ha offerten…",
    );
  });

  it("never cuts inside a word", () => {
    expect(clipAtWord("alpha beta gamma delta", room(12))).toBe("alpha beta…");
  });

  it("drops the punctuation before the ellipsis", () => {
    expect(clipAtWord("Ingen garanti. Kunden ringer upp igen.", room(16))).toBe(
      "Ingen garanti…",
    );
    expect(clipAtWord("ett, två; tre – fyra", room(14))).toBe("ett, två; tre…");
  });

  it("gives only the ellipsis when not even the first word fits", () => {
    expect(clipAtWord("extraordinärlångtord och mer", room(5))).toBe("…");
  });

  it("cuts inside a word longer than a word can be, such as a URL", () => {
    const url = "https://example.com/very/long/path/to/a/page";
    expect(clipAtWord(`Kunden ringde ${url} igen`, room(30))).toBe(
      `Kunden ringde ${url.slice(0, 15)}…`,
    );
  });
});
