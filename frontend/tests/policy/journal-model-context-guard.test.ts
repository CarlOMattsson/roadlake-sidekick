// D-058 (see docs/decisions/log.md): journal text must not reach the model context.
// updateModelContext is the channel from an MCP app into the host model's context, so the journal
// app may not use it or console at all, and no feature may pass the journal content fields
// (summary, key_points, raw_text) to it. onModelContext is the same channel as a prop of the rooms
// and the shell, so the same rules apply to it.
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  featuresDir,
  readText,
  sourceFiles,
} from "@tests/helpers/source-files";

const journalAppDir = path.join(featuresDir, "journal-app");

// Reviewed exception, keyed by "<relative file>:<argument text>". The work board summary
// (work-app/board/board-summary.tsx) is passed as the bare identifier `summary`. It is board data,
// never journal content. Any other argument containing a journal field is a violation.
const reviewedBoardSummaryCalls = new Set<string>([
  "work-app/room.tsx:summary",
]);

const journalFields = /\b(summary|key_points|raw_text)\b/;

// A real call of the channel: `updateModelContext(`, `onModelContext(`, `onModelContext?.(`, or
// `modelContext.current?.(` (the ref sidekick-shell.tsx keeps the prop in). A prop type such as
// `onModelContext?: (summary: string) => void` and a JSX attribute `onModelContext={...}` do not
// match, because no `(` follows the name there.
const modelContextCallStart =
  /\b(?:updateModelContext|onModelContext)\s*(?:\?\.)?\s*\(|\bmodelContext\.current\?\.\s*\(/g;

type SourceFile = { rel: string; source: string };
type ModelContextCall = { rel: string; args: string };

function loadSources(dir: string): SourceFile[] {
  return sourceFiles(dir, /\.tsx?$/).map((file) => ({
    rel: path.relative(featuresDir, file).split(path.sep).join("/"),
    source: readText(file),
  }));
}

// Returns the argument text of each model-context call. A method definition
// (`updateModelContext(summary) {`) is not a call and is skipped.
function modelContextCalls({ rel, source }: SourceFile): ModelContextCall[] {
  const calls: ModelContextCall[] = [];
  for (const match of source.matchAll(modelContextCallStart)) {
    const open = (match.index ?? 0) + match[0].length - 1;
    let depth = 0;
    let close = -1;
    for (let i = open; i < source.length; i++) {
      const ch = source[i];
      if (ch === "(") depth++;
      else if (ch === ")") {
        depth--;
        if (depth === 0) {
          close = i;
          break;
        }
      }
    }
    if (close === -1)
      throw new Error(`Unbalanced model-context call in ${rel}`);
    if (source.slice(close + 1).trimStart()[0] === "{") continue;
    calls.push({ rel, args: source.slice(open + 1, close).trim() });
  }
  return calls;
}

// The calls whose argument carries a journal field and is not the reviewed board exception.
function journalFieldViolations(list: ModelContextCall[]): string[] {
  return list
    .filter(
      (c) =>
        journalFields.test(c.args) &&
        !reviewedBoardSummaryCalls.has(`${c.rel}:${c.args}`),
    )
    .map((c) => `${c.rel}: modelContext(${c.args})`);
}

describe("D-058: journal text never reaches the model context", () => {
  const all = loadSources(featuresDir);
  const journal = all.filter((f) => f.rel.startsWith("journal-app/"));
  const calls = all.flatMap(modelContextCalls);

  it("scans the journal app and finds model-context calls elsewhere", () => {
    expect(sourceFiles(journalAppDir, /\.tsx?$/).length).toBeGreaterThan(0);
    expect(calls.length).toBeGreaterThan(0);
  });

  it("journal-app never references updateModelContext, onModelContext or console", () => {
    const offenders = journal
      .filter((f) =>
        /\b(?:updateModelContext|onModelContext)\b|\bconsole\s*\./.test(
          f.source,
        ),
      )
      .map((f) => f.rel);
    expect(offenders).toEqual([]);
  });

  it("no feature passes summary, key_points or raw_text to a model-context call", () => {
    expect(journalFieldViolations(calls)).toEqual([]);
  });

  it("no journal-app or sidekick shell file passes summary, key_points or raw_text to a model-context call", () => {
    const own = calls.filter(
      (c) =>
        c.rel.startsWith("journal-app/") ||
        c.rel.startsWith("mcp-apps/sidekick-"),
    );
    expect(own.length).toBeGreaterThan(0);
    expect(journalFieldViolations(own)).toEqual([]);
  });

  it("the reviewed exception still matches a real call (stale entries fail)", () => {
    const found = new Set(calls.map((c) => `${c.rel}:${c.args}`));
    for (const key of reviewedBoardSummaryCalls) {
      expect([...found]).toContain(key);
    }
  });
});
