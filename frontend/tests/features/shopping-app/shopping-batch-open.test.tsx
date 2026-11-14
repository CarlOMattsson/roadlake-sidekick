import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import { preloadSidekickApp } from "@tests/helpers/preload-sidekick-app";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

type HostContextListener = (context: {
  displayMode?: string;
  availableDisplayModes?: string[];
}) => void;

// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  hostContext: [] as HostContextListener[],
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
    onToolInput: () => undefined,
    onToolCancelled: () => undefined,
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: (listener: HostContextListener) => {
      host.hostContext.push(listener);
    },
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
  version: 1,
  purchased: false,
};

const detail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk],
};

// The app's modules load at collection time, which has no timeout; the entry import in beforeAll then only
// runs the entry itself.
await preloadSidekickApp();

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  // The app reads its language once, when sidekick-entry is imported, so the Sidekick setting goes in first.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    availableDisplayModes: ["inline", "fullscreen"],
  });
  host.requestDisplayMode.mockResolvedValue("fullscreen");
  // The list tools answer; the write tools never run in this test.
  host.call.mockImplementation((name: string) => {
    if (name === "list_shopping_lists")
      return Promise.resolve({ lists: [list], next_offset: null });
    if (name === "get_shopping_list") return Promise.resolve(detail);
    return new Promise(() => undefined);
  });
  await import("@/features/mcp-apps/sidekick-entry");
});

/** Delivers one tool result to the mounted app, as the host does after a model tool call. */
function deliver(structuredContent: unknown) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError: false });
  });
}

it("a long batch with Open shows three names and counts the rest in the Open foot", () => {
  deliver({
    items: Array.from({ length: 10 }, (_, n) => ({
      client_ref: String(n),
      item: {
        ...milk,
        id: `${milk.id.slice(0, -2)}${n + 10}`,
        name: `Item ${n + 1}`,
      },
    })),
    evaluated_on: "2026-10-24",
    list_name: "Veckohandel",
  });
  const names = document.querySelector(".shopping-batch-names");
  expect(names?.querySelectorAll("li")).toHaveLength(3);
  expect(names).toHaveTextContent("Item 3");
  expect(names).not.toHaveTextContent("Item 4");
  // The count of the names left out stands after the button's name, not as a row of its own.
  expect(
    screen.getByRole("button", { name: new RegExp(`^${shoppingEn.openList}`) }),
  ).toHaveTextContent(`${shoppingEn.openList} · 7 more added`);
  expect(screen.queryByText(shoppingEn.moreItems(7))).not.toBeInTheDocument();
  // The count is of the items just added, which the list card's "open items" count is not: the words say so.
  expect(shoppingSv.hiddenAdded(11)).toBe("11 fler tillagda");
  expect(shoppingEn.hiddenAdded(11)).toBe("11 more added");
});

it("Open on an add card opens fullscreen with that list selected and read", async () => {
  const user = userEvent.setup();
  deliver({
    items: [{ client_ref: "0", item: milk }],
    evaluated_on: "2026-10-24",
    list_name: "Veckohandel",
  });
  // The host offered fullscreen in its initial context, so the inline card has Open.
  await user.click(screen.getByRole("button", { name: shoppingEn.openList }));
  expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
  // The host grants fullscreen.
  act(() => {
    for (const listener of host.hostContext)
      listener({ displayMode: "fullscreen" });
  });
  // The list is read by its id from the result, and the store view replaces the chooser.
  expect(
    await screen.findByRole("heading", { level: 2, name: "Veckohandel" }),
  ).toBeInTheDocument();
  expect(host.call).toHaveBeenCalledWith(
    "get_shopping_list",
    expect.objectContaining({ list_id: list.id }),
  );
  expect(
    screen.getByRole("button", { name: /^Mark Milk as/ }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});
