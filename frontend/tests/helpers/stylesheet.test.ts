import { describe, expect, it } from "vitest";

import { Stylesheet } from "./stylesheet";
import { sourceFiles } from "./source-files";

function element(html: string): Element {
  document.body.innerHTML = html;
  return document.body.firstElementChild as Element;
}

describe("Stylesheet parsing", () => {
  const sheet = new Stylesheet(`
    /* a comment with { braces } and a rule: .ghost { color: red; } */
    @import url("x.css");
    .a { color: red; background: url("data:image/png;base64,AAA"); }
    .a,
    .b > .c { margin: 0   2px; --token: var(--x,   light-dark(#fff,#000)); }
    @media (max-width: 24rem) { .a { color: blue; } }
    @container sk-frame (min-width: 640px) {
      @supports (display: grid) { .a { display: grid; } }
    }
    @keyframes pulse { from { opacity: 0; } 50% { opacity: .5; } to { opacity: 1; } }
    @font-face { font-family: X; src: url(x.woff); }
  `);

  it("reads declarations, ignoring comments, strings with semicolons and at-rules without selectors", () => {
    expect(sheet.rule(".a")).toEqual({
      color: "red",
      background: 'url("data:image/png;base64,AAA")',
      margin: "0 2px",
      "--token": "var(--x, light-dark(#fff, #000))",
    });
    expect(sheet.has(".ghost")).toBe(false);
  });

  it("finds a rule by any selector of its list, or by a whole list", () => {
    expect(sheet.rule(".b > .c").margin).toBe("0 2px");
    expect(sheet.rule(".b>.c").margin).toBe("0 2px");
    expect(sheet.rule(".a, .b > .c").margin).toBe("0 2px");
    expect(sheet.has(".a, .missing")).toBe(false);
  });

  it("keeps rules inside at-rules apart, nested conditions included", () => {
    expect(sheet.rule(".a", ["@media (max-width: 24rem)"])).toEqual({
      color: "blue",
    });
    expect(
      sheet.rule(".a", [
        "@container sk-frame (min-width: 640px)",
        "@supports (display: grid)",
      ]),
    ).toEqual({ display: "grid" });
  });

  it("reads @keyframes steps in order", () => {
    expect(sheet.keyframes("pulse").map((step) => step.selector)).toEqual([
      "from",
      "50%",
      "to",
    ]);
    expect(() => sheet.keyframes("missing")).toThrow("no @keyframes missing");
  });

  it("says which selectors look similar when a rule is missing", () => {
    expect(() => sheet.rule(".c")).toThrow(/no rule for "\.c"; similar: /);
  });

  it("rejects nested rules instead of misreading them", () => {
    expect(() => new Stylesheet(".a { .b { color: red; } }")).toThrow(
      "nested rules are not supported",
    );
  });
});

describe("Stylesheet.styleOf", () => {
  const sheet = new Stylesheet(`
    .card { color: red; padding: 1px; }
    .room .card { color: green; }
    .card { color: blue; margin: 0; }
    .card[data-state="open"] { padding: 4px; }
    :where(.room) .card { margin: 9px; }
    :is(.room, #id) .nested { border: 0; }
    .card::before { content: "x"; }
    .card:hover { color: pink; }
    @media (max-width: 24rem) { .card { padding: 2px; } }
  `);

  it("applies the more specific selector over a later one, and the later one among equals", () => {
    const card = element('<div class="card"></div>');
    // Without the room, only `.card` rules apply: the later one wins on colour.
    expect(sheet.styleOf(card)).toEqual({
      color: "blue",
      padding: "1px",
      margin: "0",
    });
    // With it, `.room .card` outranks both `.card` rules.
    expect(sheet.styleOf(card, { room: "room" }).color).toBe("green");
    // `:where()` adds no specificity, so the later `.card` rule's source order decides between equals.
    expect(sheet.styleOf(card, { room: "room" }).margin).toBe("9px");
  });

  it("removes the room class again and matches attributes", () => {
    const card = element('<div class="card" data-state="open"></div>');

    expect(sheet.styleOf(card, { room: "room" }).padding).toBe("4px");
    expect(document.documentElement.classList.contains("room")).toBe(false);
  });

  it("takes a rule's specificity from the widest argument of :is()", () => {
    document.body.innerHTML =
      '<div class="room"><p class="nested" id="id"></p></div>';
    const nested = document.querySelector(".nested") as Element;

    expect(sheet.styleOf(nested).border).toBe("0");
  });

  it("applies at-rule rules only in their own context, and pseudo-elements only when asked for", () => {
    const card = element('<div class="card"></div>');

    expect(
      sheet.styleOf(card, { conditions: ["@media (max-width: 24rem)"] }),
    ).toEqual({ padding: "2px" });
    expect(sheet.styleOf(card, { pseudo: "::before" })).toEqual({
      content: '"x"',
    });
    expect(sheet.styleOf(card).content).toBeUndefined();
  });

  it("never applies a pseudo-class jsdom cannot match", () => {
    const card = element('<div class="card"></div>');

    expect(sheet.styleOf(card).color).not.toBe("pink");
  });
});

describe("sourceFiles", () => {
  it("lists matching files recursively and sorted, and nothing for a missing directory", () => {
    const files = sourceFiles(undefined, /\.css$/);

    expect(files.length).toBeGreaterThan(0);
    expect(files).toEqual([...files].sort());
    expect(files.every((file) => file.endsWith(".css"))).toBe(true);
    expect(sourceFiles("/does/not/exist")).toEqual([]);
  });
});
