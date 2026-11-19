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
  it("expose onOpenItem or onOpenContact, so a row opens its record and not just the room", () => {
    const missing = summaryFiles().filter((file) => {
      const source = readText(file);
      return (
        /<InlineRow[\s>]/.test(source) &&
        !source.includes("onOpenItem") &&
        !source.includes("onOpenContact")
      );
    });
    expect(missing).toEqual([]);
  });

  it("send a named Contact to the full view as its target, and never ask for fullscreen without it", () => {
    const source = readText(
      path.join(featuresDir, "work-app", "view", "work-view.tsx"),
    );
    const body = source.slice(source.indexOf("const openContactFullscreen"));
    const handler = body.slice(0, body.indexOf("\n      : undefined;"));
    expect(handler).toContain("openRecord(");
    expect(handler).not.toContain("fullscreen?.(");
  });

  it("draw a Journal link chip that cannot open as a plain name, not as a frame that looks pressed", () => {
    const links = readText(
      path.join(featuresDir, "journal-app", "entry-links.tsx"),
    );
    const css = readText(path.join(featuresDir, "journal-app", "journal.css"));
    // Both kinds of link have a way to open; a chip without one gets the plain look.
    expect(links).toContain("onOpenContact");
    expect(links).toContain("onOpenProject");
    expect(links).toContain("journal-chip--static");
    expect(css).toContain(".journal-chip.journal-chip--static");
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
