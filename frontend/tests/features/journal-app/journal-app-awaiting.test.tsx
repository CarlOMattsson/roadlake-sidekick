import { act, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { journalEn } from "@/features/journal-app/labels";
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

describe("journal app awaiting state", () => {
  it("shows AwaitingResult, not the empty text, until the first tool result", async () => {
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true"),
    );
    expect(screen.queryByText(journalEn.empty)).not.toBeInTheDocument();

    // A single entry card is the first tool result: the awaiting state ends.
    act(() => {
      for (const listener of host.toolResult)
        listener({
          structuredContent: {
            entry: {
              id: "019f0000-0000-7000-8000-0000000000e1",
              title: "Mötet om offerten",
              summary: null,
              contact_ids: [],
              task_ids: [],
            },
          },
          isError: false,
        });
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "Mötet om offerten" }),
    ).toBeInTheDocument();
    expect(
      document.querySelector('[role="status"][aria-busy="true"]'),
    ).toBeNull();
  });
});
