// The row › in Dagbok is the shared row glyph: --sk-chevron wide and high (24, 16 on a narrow frame), as in the
// other rooms, instead of the icon's own 24 px at every width. Reads the stylesheet through the shared reader.
import { describe, expect, it } from "vitest";

import { readStylesheet } from "./helpers/stylesheet";

const css = readStylesheet("features/journal-app/journal.css");

describe("Dagbok row chevron", () => {
  it("is sized by the shared --sk-chevron token in both axes", () => {
    expect(
      css.rule(".sidekick-journal .journal-entry-chevron svg"),
    ).toMatchObject({
      width: "var(--sk-chevron)",
      height: "var(--sk-chevron)",
    });
  });

  it("turns 16 on a narrow frame as the contact and shopping rows do", () => {
    expect(
      css.rule(".sidekick-journal", [
        "@container sk-frame (max-width: 399.98px) or (max-width: 17.25rem)",
      ])["--sk-chevron"],
    ).toBe("16px");
  });
});
