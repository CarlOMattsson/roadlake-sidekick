import { act, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import { preloadSidekickApp } from "@tests/helpers/preload-sidekick-app";

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
    initialize: host.initialize,
    call: vi.fn(() => new Promise(() => undefined)),
    requestDisplayMode: vi.fn(() => Promise.resolve("inline")),
    updateModelContext: vi.fn(),
    getFeatures: () => ({
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
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

beforeAll(async () => {
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({ locale: "en-GB" });
  await import("@/features/mcp-apps/sidekick-entry");
});

describe("work app awaiting state", () => {
  it("shows AwaitingResult, not the empty text, until the first tool result", async () => {
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true"),
    );
    expect(screen.queryByText(workEn.empty)).not.toBeInTheDocument();

    // An error result is a first tool result too: the awaiting state ends and the error frame shows.
    act(() => {
      for (const listener of host.toolResult)
        listener({ structuredContent: undefined, isError: true });
    });
    expect(
      document.querySelector('[role="status"][aria-busy="true"]'),
    ).toBeNull();
  });
});
