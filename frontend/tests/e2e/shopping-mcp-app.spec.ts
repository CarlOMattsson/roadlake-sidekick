// Playwright runs this file outside Vitest: it reads the bundled app HTML (and font files) from disk to serve them to the simulated host.
import { readFileSync } from "node:fs";
import { withAppLocale } from "./mcp-host-fixture";
import { test, expect } from "@playwright/test";

test("sandboxed MCP App initializes, reads and writes through the host on a mobile viewport", async ({
  page,
}) => {
  const html = withAppLocale(
    readFileSync("../backend/src/sidekick/mcp/apps/sidekick.html", "utf8"),
    "en",
  );
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  // Without allow-forms the browser reports a blocked form submit as a console error, not a page error.
  const consoleMessages: string[] = [];
  page.on("console", (message) => consoleMessages.push(message.text()));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setContent(
    '<iframe title="Sidekick shopping" sandbox="allow-scripts" style="width:360px;height:750px;border:0"></iframe>',
  );
  await page.evaluate((resource) => {
    const frame = document.querySelector("iframe")!;
    const list = {
      id: "019f0000-0000-7000-8000-000000000001",
      name: "IKEA someday",
      version: 1,
      archived: false,
      created_at: "2026-10-24T12:00:00Z",
      updated_at: "2026-10-24T12:00:00Z",
    };
    const item = {
      id: "019f0000-0000-7000-8000-000000000002",
      list_id: list.id,
      name: '<img src="https://example.org/tracker" onerror="alert(1)">',
      quantity: "1",
      unit: null,
      store: "IKEA",
      note: null,
      recipient_contact_id: null,
      occasion: null,
      target_date: null,
      product_url: null,
      offer: null,
      offer_status: "none",
      purchased: false,
      purchased_at: null,
      version: 1,
      created_at: list.created_at,
      updated_at: list.updated_at,
    };
    const state = {
      calls: [] as { name: string; arguments: Record<string, unknown> }[],
      initialized: false,
    };
    Object.assign(window, { shoppingTest: state });
    const items = [item];
    const detail = () => ({
      shopping_list: list,
      items,
      next_offset: null,
      evaluated_on: "2026-10-24",
    });
    window.addEventListener("message", (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data as {
        id?: number;
        method: string;
        params: { name: string; arguments: Record<string, unknown> };
      };
      const reply = (result: object) =>
        frame.contentWindow!.postMessage(
          { jsonrpc: "2.0", id: message.id, result },
          "*",
        );
      if (message.method === "ui/initialize")
        reply({
          protocolVersion: "2026-01-26",
          hostCapabilities: {},
          hostInfo: { name: "Test host", version: "1" },
          hostContext: { locale: "en", theme: "light" },
        });
      else if (message.method === "ui/notifications/initialized") {
        state.initialized = true;
        frame.contentWindow!.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { structuredContent: detail() },
          },
          "*",
        );
      } else if (message.method === "tools/call") {
        state.calls.push(message.params);
        const { name } = message.params;
        if (name === "list_shopping_lists")
          reply({ structuredContent: { lists: [list], next_offset: null } });
        else if (name === "get_shopping_list")
          reply({ structuredContent: detail() });
        else if (name === "set_shopping_item_purchased") {
          item.purchased = true;
          item.version++;
          reply({ structuredContent: { item, evaluated_on: "2026-10-24" } });
        } else if (name === "add_shopping_items") {
          const entries = message.params.arguments.items as { name: string }[];
          for (const entry of entries)
            items.push({
              ...item,
              id: `019f0000-0000-7000-8000-${String(100 + items.length).padStart(12, "0")}`,
              name: entry.name,
              purchased: false,
              version: 1,
            });
          reply({ structuredContent: { items: [] } });
        } else reply({ isError: true });
      }
    });
    frame.srcdoc = resource;
  }, html);
  const app = page.frameLocator("iframe");
  await expect(
    app.getByRole("heading", { name: "IKEA someday" }),
  ).toBeVisible();
  await expect(app.locator("img")).toHaveCount(0);
  // The resource must carry its stylesheet; an empty inlined <style> once shipped unstyled.
  await expect(app.locator(".sidekick-shopping")).toHaveCSS(
    "padding-top",
    "16px",
  );
  await app.getByRole("checkbox").click();
  // A purchased item stays in its place while its Undo holds: the row's meta line says "Bought" and "Undo" is a
  // compact secondary button in the row (`li .shopping-undo`). The item is also listed in the collapsed "Bought (n)"
  // group. A closed <details> is not in the accessibility tree, so open the group first.
  await expect(app.getByText("Bought (1)", { exact: true })).toBeVisible();
  await app.getByText("Bought (1)", { exact: true }).click();
  // Two checkboxes now show the item. The one in place is the only row that holds an Undo.
  const heldRow = app
    .getByRole("listitem")
    .filter({ has: app.getByRole("button", { name: /^Undo:/ }) });
  await expect(heldRow).toHaveCount(1);
  // The folded inline row shows the name, the Undo and no status line (.shopping-items--folded hides it).
  await expect(heldRow.getByRole("button", { name: /^Undo:/ })).toBeVisible();
  await expect(heldRow.getByRole("checkbox")).toBeChecked();
  // Enter in the add field (one line in the inline view) adds the items. The App iframe has no allow-forms, so a form submit would be blocked.
  const addField = app.getByRole("textbox", { name: "Items", exact: true });
  await addField.fill("Bread");
  await addField.press("Enter");
  await expect(app.getByText("Bread", { exact: true })).toBeVisible();
  await expect(addField).toHaveValue("");
  const state = await page.evaluate(
    () =>
      (
        window as unknown as {
          shoppingTest: {
            initialized: boolean;
            calls: { name: string; arguments: Record<string, unknown> }[];
          };
        }
      ).shoppingTest,
  );
  expect(state.initialized).toBe(true);
  const purchase = state.calls.find(
    (call) => call.name === "set_shopping_item_purchased",
  )!;
  expect(purchase.arguments).toMatchObject({ purchased: true, version: 1 });
  expect(purchase.arguments.idempotency_key).toBeTruthy();
  const added = state.calls.find((call) => call.name === "add_shopping_items")!;
  expect(added.arguments).toMatchObject({
    list_id: "019f0000-0000-7000-8000-000000000001",
    items: [{ name: "Bread", client_ref: "0" }],
  });
  expect(added.arguments.idempotency_key).toBeTruthy();
  expect(consoleMessages.filter((text) => /sandbox/i.test(text))).toEqual([]);
  const dimensions = await app.locator("body").evaluate((body) => ({
    width: body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  expect(failures).toEqual([]);
  expect(networkRequests).toBe(0);
});
