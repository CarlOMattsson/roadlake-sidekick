import { act, screen } from "@testing-library/react";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { shoppingEn } from "@/features/shopping-app/labels";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  initialize: vi.fn(),
  call: vi.fn(),
  requestDisplayMode: vi.fn(),
}));

vi.mock("@/features/mcp-apps/bridge", () => ({
  createHostBridge: () => ({
    getFeatures: () => ({
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
    initialize: host.initialize,
    call: host.call,
    requestDisplayMode: host.requestDisplayMode,
    updateModelContext: vi.fn(),
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: () => undefined,
    onTeardown: () => undefined,
  }),
}));

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

const milk = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  list_id: list.id,
  name: "Milk",
  quantity: "2",
  unit: "l",
  store: "ICA",
  version: 1,
  purchased: false,
};

const detail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk],
};

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  // The host offers fullscreen, yet the shop view must not wait for Open.
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    availableDisplayModes: ["inline", "fullscreen"],
  });
  host.call.mockImplementation((name: string) => {
    if (name === "list_shopping_lists")
      return Promise.resolve({ lists: [list], next_offset: null });
    if (name === "get_shopping_list")
      return Promise.resolve({ ...detail, store: "ICA" });
    return new Promise(() => undefined);
  });
  await import("@/features/mcp-apps/sidekick-entry");
});

it("a list read for a store opens the shop view inline, with no Open button", async () => {
  act(() => {
    for (const listener of host.toolResult)
      listener({
        structuredContent: { ...detail, store: "ICA" },
        isError: false,
      });
  });
  expect(
    await screen.findByRole("button", { name: /^Mark Milk as/ }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: shoppingEn.openList }),
  ).not.toBeInTheDocument();
  // The opening result carries the list: it is not read again, only the register of lists is read.
  expect(host.call).not.toHaveBeenCalledWith(
    "get_shopping_list",
    expect.anything(),
  );
});
