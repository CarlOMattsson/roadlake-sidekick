// Comments in frontend code are English (language policy, 2026-11-10). This mirrors
// backend/tests/policy/test_no_swedish_comments.py.
//
// Swedish is for the user interface and its data, which live in string literals, JSX text and
// i18n catalogs; none of those are looked at here. Only `//` and `/* */` comments are checked,
// found with the TypeScript parser so that comment-like text inside strings, template literals
// and regular expressions is never mistaken for a comment. Swedish names and data may still
// appear inside a comment: text in quotes or backticks, capitalized words (room and screen
// names such as Inköp or Dagbok) and single letters are ignored. Any other word with å, ä or ö
// fails, and so do a few common Swedish words that have none of those letters.
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import {
  entryNames,
  frontendDir,
  readText,
  sourceFiles,
} from "@tests/helpers/source-files";

const roots = ["src", "tests"];
// Screenshot scripts, run by hand and not part of the test suite.
const skippedDirs = new Set(["node_modules", "dist", "ux"]);
const sourceFile = /\.(ts|tsx|mts|cts)$/;

const quoted = /`[^`]*`|"[^"]*"|“[^”]*”|«[^»]*»/g;
// Lowercase only: capitalized words are names.
const swedishLetterWord =
  /(?<![\p{L}\p{N}_])(?=[\p{L}]*[åäö])[a-zåäö]{2,}(?![\p{L}\p{N}_])/u;
const plainWordList =
  "och|inte|eller|eftersom|alltid|aldrig|bara|utan|ingen|inga|sedan|samma|vilket|annars|redan|kunna|finns|visas|skapa|ska";
const swedishPlainWords = new RegExp(
  `(?<![\\p{L}\\p{N}_-])(?:${plainWordList})(?![\\p{L}\\p{N}_-])`,
  "u",
);
// Anything isSwedish accepts contains one of these, and finding one is far cheaper than isSwedish itself.
const swedishHint = new RegExp(`[åäö]|${plainWordList}`);

function scannedFiles(dir: string): string[] {
  return sourceFiles(
    dir,
    (name) => sourceFile.test(name) && !name.endsWith(".d.ts"),
    [...skippedDirs],
  );
}

function configFiles(): string[] {
  return entryNames(
    frontendDir,
    /^(vite|vitest|playwright|capacitor)[\w.-]*\.config\.(ts|mts|js|mjs)$/,
  ).map((name) => path.join(frontendDir, name));
}

type Comment = { line: number; text: string };

function commentsOf(fileName: string, source: string): Comment[] {
  const kind = fileName.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const file = ts.createSourceFile(
    fileName,
    source,
    ts.ScriptTarget.Latest,
    true,
    kind,
  );
  const seen = new Set<number>();
  const comments: Comment[] = [];
  const collect = (ranges: readonly ts.CommentRange[] | undefined) => {
    for (const range of ranges ?? []) {
      if (seen.has(range.pos)) continue;
      seen.add(range.pos);
      // Quoted text is removed from the whole comment first, so a quote may span lines.
      const raw = source
        .slice(range.pos, range.end)
        .replace(quoted, (span) => span.replace(/[^\n]/g, " "));
      const start = file.getLineAndCharacterOfPosition(range.pos).line + 1;
      raw
        .split("\n")
        .forEach((text, offset) =>
          comments.push({ line: start + offset, text }),
        );
    }
  };
  // getChildren includes tokens such as the closing brace of a JSX `{/* ... */}` expression, so
  // every comment is either leading or trailing trivia of some node or token.
  const visit = (node: ts.Node) => {
    if (node.kind !== ts.SyntaxKind.JsxText) {
      collect(ts.getLeadingCommentRanges(source, node.pos));
      collect(ts.getTrailingCommentRanges(source, node.end));
    }
    for (const child of node.getChildren(file)) visit(child);
  };
  visit(file);
  return comments.sort((a, b) => a.line - b.line);
}

function isSwedish(text: string): boolean {
  return swedishLetterWord.test(text) || swedishPlainWords.test(text);
}

/**
 * A cheap, conservative test for whether a file can hold a Swedish comment, so the TypeScript parser only runs on
 * files that might. It only ever says "no" for a file where `commentsOf` plus `isSwedish` would also find nothing:
 * every comment line the check can flag contains Swedish text and either holds a comment marker or follows a
 * block-comment opener that has not been closed since. Strings that look like markers only make it say "maybe"
 * more often.
 */
function mayHoldSwedishComment(source: string): boolean {
  if (!swedishHint.test(source)) return false;
  let blockOpen = false;
  return source.split("\n").some((line) => {
    const opened = line.lastIndexOf("/*");
    const closed = line.lastIndexOf("*/");
    const mayBeComment = blockOpen || opened >= 0 || line.includes("//");
    const candidate = mayBeComment && swedishHint.test(line) && isSwedish(line);
    if (opened >= 0 || closed >= 0) {
      // `/*/` opens a block comment: its slash cannot also close it.
      blockOpen = opened >= 0 && closed < opened + 2;
    }
    return candidate;
  });
}

describe("frontend comments are English", () => {
  it("has no Swedish comments in src, tests or the config files", () => {
    const files = [
      ...roots.flatMap((root) => scannedFiles(path.join(frontendDir, root))),
      ...configFiles(),
    ];
    const hits = files.flatMap((file) => {
      const relative = path.relative(frontendDir, file);
      const source = readText(file);
      if (!mayHoldSwedishComment(source)) return [];
      return commentsOf(file, source)
        .filter((comment) => isSwedish(comment.text))
        .map(
          (comment) =>
            `${relative}:${comment.line}: ${comment.text.trim().slice(0, 100)}`,
        );
    });
    expect(
      hits,
      `Swedish comments (write English):\n${hits.join("\n")}`,
    ).toEqual([]);
    // Parses the source files that might hold a Swedish comment with the TypeScript compiler.
  }, 60_000);

  it("finds Swedish comments but not strings, template literals or JSX text", () => {
    const sample = [
      "const label = 'Köp licens'; // Swedish UI text is fine in a string",
      "// en kommentar på svenska",
      "const t = `// inte en kommentar ${label}`;",
      "/* Visa listan och",
      "   spara sedan. */",
      "const re = /och|på/;",
      "export const el = <p>Öppna och läs {/* öppnar rummet */}</p>;",
      '// The Inköp room shows "Köp" and `på` as data.',
    ].join("\n");
    const flagged = commentsOf("sample.tsx", sample)
      .filter((comment) => isSwedish(comment.text))
      .map((comment) => comment.line);
    expect(flagged).toEqual([2, 4, 5, 7]);
  });

  it("skips parsing only for files that cannot hold a Swedish comment", () => {
    expect(mayHoldSwedishComment("const label = 'Köp och sälj';")).toBe(false);
    expect(mayHoldSwedishComment("// Only English here\nconst a = 1;")).toBe(
      false,
    );
    expect(mayHoldSwedishComment("const a = 1; // inte engelska")).toBe(true);
    expect(mayHoldSwedishComment("/* Only English */\nconst a = 'på';")).toBe(
      false,
    );
    expect(mayHoldSwedishComment("/*\n en kommentar på\n svenska */")).toBe(
      true,
    );
  });
});
