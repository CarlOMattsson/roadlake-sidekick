import { expect, test, type FrameLocator } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { settled } from "./mcp-host-fixture";
import { bigContactContext, workReplies } from "./one-screen-fixtures";

// The Contact editor's layout in a real Chromium on the simulated host (mcp-host-fixture.ts), not a real Claude or
// Android host: every tool answer is a fixture. The action row never covers a field, and after Save the name heading
// is whole, not under the rows that stay on top while the view scrolls.

const saved = {
  contact: {
    ...bigContactContext.contact,
    role: "Grundare och delägare",
    version: 3,
  },
};
const replies = {
  ...workReplies,
  update_contact: { structuredContent: saved },
};

async function openEditor(
  page: Parameters<typeof openSidekick>[0],
  width: number,
  theme: "light" | "dark",
) {
  const opened = await openSidekick(page, {
    width,
    theme,
    tool: "get_contact_context",
    result: bigContactContext,
    replies,
  });
  await settled(opened.app);
  // The Contact's own ⋯: at 1440 the card opens beside the Contacts list, whose head has a ⋯ too.
  await opened.app
    .getByRole("button", { name: "Fler val", exact: true })
    .and(opened.app.locator(".work-detail-action"))
    .click();
  await opened.app
    .getByRole("button", { name: "Redigera", exact: true })
    .click();
  await expect(
    opened.app.getByRole("form", { name: "Redigera" }),
  ).toBeVisible();
  return opened;
}

/** The ids of the form's fields that the action row overlaps (viewport coordinates). */
function overlaps(app: FrameLocator) {
  return app.locator("form.work-contact-edit").evaluate((form) => {
    const row = form.querySelector(".sk-form-actions")?.getBoundingClientRect();
    if (!row) return ["no action row"];
    return [...form.querySelectorAll("input, textarea")]
      .filter((field) => {
        const r = field.getBoundingClientRect();
        return r.width > 0 && r.top < row.bottom && r.bottom > row.top;
      })
      .map((field) => field.id);
  });
}

for (const width of [1440, 390]) {
  for (const theme of ["light", "dark"] as const) {
    test(`Contact editor at ${width} px, ${theme}: the action row covers no field wherever the view is scrolled`, async ({
      page,
    }) => {
      const { app, failures } = await openEditor(page, width, theme);
      const root = app.locator("html");
      const heights = await root.evaluate(() => ({
        page: document.documentElement.scrollHeight,
        view: window.innerHeight,
      }));
      for (const fraction of [0, 0.25, 0.5, 0.75, 1]) {
        await root.evaluate(
          (_, y) => window.scrollTo(0, y),
          Math.round((heights.page - heights.view) * fraction),
        );
        expect(await overlaps(app), `scrolled to ${fraction}`).toEqual([]);
      }
      // The last field, the note, is whole above the row when the view is scrolled to its end.
      await root.evaluate(() =>
        window.scrollTo(0, document.documentElement.scrollHeight),
      );
      const rowBox = await app.locator(".sk-form-actions").boundingBox();
      const noteBox = await app
        .getByLabel("Anteckning", { exact: true })
        .boundingBox();
      expect(noteBox && rowBox && noteBox.y + noteBox.height <= rowBox.y).toBe(
        true,
      );
      expect(failures).toEqual([]);
    });

    test(`Contact editor at ${width} px, ${theme}: after Save the name heading is whole and not under a row on top of the view`, async ({
      page,
    }) => {
      const { app, failures } = await openEditor(page, width, theme);
      const root = app.locator("html");
      const save = app.getByRole("button", { name: "Spara", exact: true });
      const heading = app.getByRole("heading", {
        level: 2,
        name: bigContactContext.contact.display_name,
      });
      await app
        .getByLabel("Roll", { exact: true })
        .fill("Grundare och delägare");
      // The view is a little scrolled (the heading would be partly under the strip), or at the end of the form.
      await root.evaluate(() => window.scrollTo(0, 30));
      // dispatchEvent clicks without scrolling, so the view is where the test left it when the editor closes.
      await save.dispatchEvent("click");
      await expect(heading).toBeFocused();
      await settled(app);
      // The room strip and the Back row stay on top while the view scrolls (.sk-rooms__bar, sticky): the heading
      // starts below their foot and ends inside the view.
      const bar = await app.locator(".sk-rooms__bar").boundingBox();
      const box = await heading.boundingBox();
      const view = await root.evaluate(() => innerHeight);
      expect(bar).not.toBeNull();
      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(bar!.y + bar!.height);
      expect(box!.y + box!.height).toBeLessThanOrEqual(view);
      expect(failures).toEqual([]);
    });
  }
}

test("Contact editor: Escape cancels an unchanged editor like Avbryt, and does nothing once a field is changed", async ({
  page,
}) => {
  const { app, failures } = await openEditor(page, 390, "light");
  const role = app.getByLabel("Roll", { exact: true });
  await role.fill("Något annat");
  await role.press("Escape");
  await expect(app.getByRole("form", { name: "Redigera" })).toBeVisible();
  await expect(role).toHaveValue("Något annat");
  await role.fill("Inköpschef");
  await role.press("Escape");
  await expect(app.getByRole("form", { name: "Redigera" })).toHaveCount(0);
  expect(failures).toEqual([]);
});
