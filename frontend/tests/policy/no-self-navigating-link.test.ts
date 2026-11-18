import path from "node:path";
import { describe, expect, it } from "vitest";
import { readText, sourceFiles, srcDir } from "@tests/helpers/source-files";

/**
 * The app runs in a sandboxed iframe: a plain `<a href>` that the user activates navigates the frame and blanks the
 * app. A link is either handed to the host (`onOpenLink`, ui/open-link), which cancels the click, or it opens a new
 * tab (`target="_blank"`), which a sandboxed frame without popups refuses.
 */
describe("links in the app", () => {
  it("each file that draws an anchor hands it to the host or opens it in a new tab", () => {
    const unsafe = sourceFiles(srcDir, /\.(ts|tsx)$/).filter((file) => {
      const source = readText(file);
      if (!/<a[\s>]|createElement\(["']a["']\)/.test(source)) return false;
      return !(
        source.includes('target="_blank"') ||
        source.includes('anchor.target = "_blank"') ||
        (source.includes("onOpenLink") && source.includes("preventDefault()"))
      );
    });
    expect(unsafe.map((file) => path.relative(srcDir, file))).toEqual([]);
  });
});
