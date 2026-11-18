import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  featuresDir,
  readText,
  sourceFiles,
} from "@tests/helpers/source-files";

/** Every source file under the inline cards and the board summary, where record rows are drawn. */
function summaryFiles(): string[] {
  return ["inline", "board"].flatMap((dir) =>
    sourceFiles(path.join(featuresDir, "work-app", dir), /\.tsx$/),
  );
}

describe("inline summaries with record rows", () => {
  it("expose onOpenItem, so a row opens its record and not just the room", () => {
    const missing = summaryFiles().filter((file) => {
      const source = readText(file);
      return /<InlineRow[\s>]/.test(source) && !source.includes("onOpenItem");
    });
    expect(missing).toEqual([]);
  });

  it("send the record to the full view, and never ask for fullscreen without it", () => {
    const source = readText(
      path.join(featuresDir, "work-app", "view", "work-view.tsx"),
    );
    const body = source.slice(source.indexOf("const openRecordFullscreen"));
    const handler = body.slice(0, body.indexOf("\n  };"));
    // The room asks the host for fullscreen with this target; a bare fullscreen() opens the room's start view.
    expect(handler).toContain("openRecord?.(");
    expect(handler).not.toContain("fullscreen?.(");
  });
});
