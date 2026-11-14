import { expect, test } from "@playwright/test";
import { openSidekick } from "./app-navigation-fixtures";
import { box, resolved, style } from "./computed-style";
import {
  deliverToolResult,
  effectiveTargetSize,
  openSimulatedApp,
  readBuiltApp,
  settled,
  waitForAppInitialized,
} from "./mcp-host-fixture";
import { bigTrash, controlReplies, sItem, sList } from "./one-screen-fixtures";

// Rows of Kontroll and Shopping measured in a real Chromium from computed style and boxes. Simulated host (see
// mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture.

test("Kontroll: the title is a visible h2 in the title type under the Back row, and each row is the row template with its action across both lines", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "list_trash",
    result: bigTrash,
    replies: controlReplies,
  });
  await settled(app);
  const title = app.getByRole("heading", {
    level: 2,
    name: "Minne och kontroll",
  });
  await expect(title).toBeVisible();
  const heading = await app.locator("#root").evaluate((root) => {
    const probe = document.createElement("span");
    root.appendChild(probe);
    probe.style.font = "var(--sk-type-title)";
    const computed = getComputedStyle(probe);
    const out = {
      fontSize: computed.fontSize,
      fontWeight: computed.fontWeight,
    };
    probe.remove();
    return out;
  });
  expect(
    await style(
      title,
      "fontSize",
      "fontWeight",
      "color",
      "marginTop",
      "position",
    ),
  ).toEqual({
    ...heading,
    color: await resolved(app, "color", "var(--sk-fg)"),
    marginTop: "-4px",
    position: "static",
  });

  const row = app.locator(".control-row").first();
  await expect(row).toBeVisible();
  const rowBox = await box(row);
  expect(rowBox.height).toBeGreaterThanOrEqual(48);
  const air = await resolved(app, "padding-top", "var(--sk-row-pad)");
  expect(await style(row, "display", "paddingTop", "paddingBottom")).toEqual({
    display: "grid",
    paddingTop: air,
    paddingBottom: air,
  });
  // One meta line, cut with an ellipsis, with no margin of its own under the title.
  const secondary = row.locator(".control-row-secondary");
  expect(
    await style(secondary, "marginTop", "whiteSpace", "textOverflow"),
  ).toEqual({
    marginTop: "0px",
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
  });
  // The action stands in the second column, centred on the row across both of its lines.
  const [action, primary, meta] = await Promise.all([
    box(row.locator(".control-row-action")),
    box(row.locator(".control-row-primary")),
    box(secondary),
  ]);
  expect(action.x).toBeGreaterThan(primary.x + primary.width - 1);
  expect(action.y + action.height / 2).toBeCloseTo(
    rowBox.y + rowBox.height / 2,
    0,
  );
  expect(meta.y).toBeGreaterThanOrEqual(primary.y + primary.height - 1);
  expect(failures).toEqual([]);
});

test("Shopping store view: a held row's Undo takes its tap target inside its own row", async ({
  page,
}) => {
  const milk = sItem(1, "Mjölk", { quantity: "2", unit: "l", store: "ICA" });
  const detail = {
    shopping_list: sList,
    items: [milk, sItem(2, "Bröd", { store: "ICA" })],
    next_offset: null,
    evaluated_on: "2026-11-13",
  };
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("shopping", "en"),
    width: 375,
    height: 800,
    hostContext: {
      locale: "en",
      theme: "light",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
    },
    replies: {
      list_shopping_lists: {
        structuredContent: { lists: [sList], next_offset: null },
      },
      get_shopping_list: { structuredContent: detail },
      set_shopping_item_purchased: {
        structuredContent: {
          item: { ...milk, purchased: true, version: 2 },
          evaluated_on: "2026-11-13",
        },
      },
    },
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, detail);
  await settled(opened.app);
  await opened.app
    .getByRole("button", { name: "Mark Mjölk as bought" })
    .click();
  const undo = opened.app.getByRole("button", { name: /^Undo bought / });
  await expect(undo).toBeVisible();
  const row = opened.app.locator(".shopping-held-item").first();
  const [rowBox, undoBox, target] = await Promise.all([
    box(row),
    box(undo),
    effectiveTargetSize(undo),
  ]);
  const reach = ((target?.height ?? undoBox.height) - undoBox.height) / 2;
  expect(reach).toBeGreaterThan(0);
  // The target (the drawn button and what its ::after adds above and below) starts on the row's top and ends inside it.
  expect(undoBox.y - reach).toBeGreaterThanOrEqual(rowBox.y - 0.5);
  expect(undoBox.y + undoBox.height + reach).toBeLessThanOrEqual(
    rowBox.y + rowBox.height + 0.5,
  );
  expect(opened.failures).toEqual([]);
});
