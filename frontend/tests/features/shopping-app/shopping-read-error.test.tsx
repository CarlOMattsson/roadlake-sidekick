import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { shoppingEn } from "@/features/shopping-app/labels";
import { preloadSidekickApp } from "@tests/helpers/preload-sidekick-app";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// The bridge is the only thing mocked. sidekick-entry keeps its state per module, so this file has its
// own import and the first tool result below is the first one the app ever sees.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  initialize: vi.fn(),
  call: vi.fn(() => new Promise(() => undefined)),
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
    requestDisplayMode: vi.fn(() => Promise.resolve("inline")),
    onToolInput: () => undefined,
    onToolCancelled: () => undefined,
    onToolResult: (listener: ToolResultListener) => {
      host.toolResult.push(listener);
    },
    onHostContext: () => undefined,
    onTeardown: () => undefined,
  }),
}));

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
  // The host names the failed tool, so the error routes to the shopping room (not to Work).
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    toolInfo: { tool: { name: "list_shopping_lists" } },
  });
  await import("@/features/mcp-apps/sidekick-entry");
});

describe("shopping app read error before any list", () => {
  it("shows the shared read notice under the app's name, not the empty list; Try again reads the lists", async () => {
    act(() => {
      for (const listener of host.toolResult)
        listener({ structuredContent: undefined, isError: true });
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t load your lists");
    // No closed code from Sidekick: the second line says that Sidekick did not answer, in exactly one sentence.
    // The host answered the tool call (a HostToolError), so it is not the connection.
    expect(alert).not.toHaveTextContent("Check your connection.");
    expect(alert).not.toHaveTextContent("You seem to be offline.");
    expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick didn’t respond.",
    );
    expect(screen.getByText(shoppingEn.title)).toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.hint)).not.toBeInTheDocument();

    // A successful read of the lists: the list view replaces the notice.
    host.call.mockResolvedValueOnce({ lists: [], next_offset: null });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(shoppingEn.noLists)).toBeInTheDocument();
    expect(screen.getByText(shoppingEn.pickerHint)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(host.call).toHaveBeenCalledWith(
      "list_shopping_lists",
      expect.any(Object),
    );
  });

  it("an error result with Sidekick's closed code says that Sidekick answered with an error", async () => {
    act(() => {
      for (const listener of host.toolResult)
        listener({ structuredContent: { code: "not_found" }, isError: true });
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t load your lists");
    expect(alert).not.toHaveTextContent("Try again in a moment.");
    expect(alert.querySelector(".sk-error-hint")).toHaveTextContent(
      "Sidekick responded with an error.",
    );
  });
});
