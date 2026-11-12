import { act, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  initialize: vi.fn(),
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
    call: vi.fn(() => new Promise(() => undefined)),
    requestDisplayMode: vi.fn(() => Promise.resolve("inline")),
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
  name: "IKEA someday",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  // The app reads its language once, when sidekick-entry is imported, so the Sidekick setting goes in first.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({ locale: "en-GB" });
  await import("@/features/mcp-apps/sidekick-entry");
});

describe("shopping app awaiting state", () => {
  it("shows AwaitingResult, not the empty text, until the first tool result", async () => {
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true"),
    );
    expect(screen.queryByText(shoppingEn.empty)).not.toBeInTheDocument();

    // A shopping list detail is the first tool result: the view replaces the awaiting state.
    act(() => {
      for (const listener of host.toolResult)
        listener({
          structuredContent: {
            shopping_list: list,
            items: [],
            next_offset: null,
            evaluated_on: "2026-10-24",
          },
          isError: false,
        });
    });
    expect(screen.getByText(shoppingEn.empty)).toBeInTheDocument();
    expect(
      document.querySelector('[role="status"][aria-busy="true"]'),
    ).toBeNull();
  });
});

/** Delivers one tool result to the mounted app, as the host does after a model tool call. */
function deliver(structuredContent: unknown) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError: false });
  });
}

/** The batch row with this full text. The prefix is a span of its own, so the row's text is matched whole. */
function batchRow(text: string) {
  return screen.getByText(
    (_content, element) =>
      element?.tagName === "LI" && element.textContent === text,
  );
}

const milk = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  list_id: list.id,
  name: "Milk",
  version: 1,
  purchased: false,
};

describe("shopping add and update results", () => {
  it("an add result shows a small card with one row per item, not the full view", () => {
    deliver({
      items: [
        { client_ref: "0", item: milk },
        {
          client_ref: "1",
          item: {
            ...milk,
            id: "019f0000-0000-7000-8000-0000000000a2",
            name: "Bread",
          },
        },
      ],
      evaluated_on: "2026-10-24",
    });
    expect(
      screen.getByRole("heading", { name: "Shopping list" }),
    ).toBeInTheDocument();
    expect(screen.getByText(shoppingEn.updatedKicker())).toBeInTheDocument();
    expect(batchRow("Added: Milk")).toBeInTheDocument();
    expect(batchRow("Added: Bread")).toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.select)).not.toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.empty)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
    // The host in this test offers no fullscreen, so the card has no Open list button.
    expect(
      screen.queryByRole("button", { name: shoppingEn.openList }),
    ).not.toBeInTheDocument();
  });

  it("an update result names the list in the heading and shows the updated item", () => {
    // update_shopping_item always answers the list name too (ItemResult), so the fixture carries it.
    deliver({
      item: { ...milk, name: "Eggs", version: 2 },
      evaluated_on: "2026-10-24",
      list_name: list.name,
    });
    expect(
      screen.getByRole("heading", { name: "IKEA someday" }),
    ).toBeInTheDocument();
    expect(batchRow("Updated: Eggs")).toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.select)).not.toBeInTheDocument();
  });

  it("a list detail replaces the batch card", () => {
    deliver({
      shopping_list: list,
      items: [],
      next_offset: null,
      evaluated_on: "2026-10-24",
    });
    expect(
      screen.queryByText(shoppingEn.updatedKicker()),
    ).not.toBeInTheDocument();
    expect(screen.getByText(shoppingEn.empty)).toBeInTheDocument();
  });

  it("has Swedish batch labels: the kicker and the fallback title", () => {
    expect(shoppingSv.updatedKicker()).toBe("Inköp · uppdaterad");
    expect(shoppingSv.listFallback).toBe("Inköpslista");
  });
});
