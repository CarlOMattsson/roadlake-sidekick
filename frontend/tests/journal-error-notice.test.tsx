import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { journalEn } from "@/features/journal-app/labels";
import { preloadSidekickApp } from "./helpers/preload-sidekick-app";

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
    initialize: host.initialize,
    call: host.call,
    requestDisplayMode: vi.fn(() => Promise.resolve("inline")),
    updateModelContext: vi.fn(),
    getFeatures: () => ({
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
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
  // The host names the tool of each result. The router routes an error by that name, since an
  // error has no shape; without a name it would land in Work.
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    toolInfo: { tool: { name: "get_journal_day" } },
  });
  await import("@/features/mcp-apps/sidekick-entry");
});

/** Today's calendar date in local time, as the app reads the day it opens on. */
function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

describe("journal app error before any view", () => {
  it("shows the shared error notice, and Try again reads today again; a failed read keeps the notice", async () => {
    const today = localToday();
    act(() => {
      for (const listener of host.toolResult)
        listener({ structuredContent: undefined, isError: true });
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t load your journal");
    // The notice sits under the app's name, like every other read error of the family.
    expect(screen.getByText(journalEn.title)).toBeInTheDocument();
    expect(screen.queryByText(journalEn.empty)).not.toBeInTheDocument();

    // A failed read: the notice stays, and the error text never reaches the screen.
    host.call.mockRejectedValueOnce(new Error("upstream detail"));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(host.call).toHaveBeenCalledWith(
        "get_journal_day",
        expect.objectContaining({
          journal_date: today,
          include_content: true,
        }),
      ),
    );
    // Lets the rejected read run its catch before the notice is checked.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn’t load your journal",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("upstream detail");

    // A successful read: the day view replaces the notice.
    host.call.mockResolvedValueOnce({
      journal_date: today,
      entries: [],
      next_cursor: null,
      summary: {
        journal_date: today,
        exists: false,
        status: null,
        content: null,
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    // Without fullscreen on offer the day shows its glance inline: an empty today says so in one line, with no count.
    expect(
      await screen.findByText(journalEn.noEntriesToday),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(journalEn.glanceEntries(0, false)),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
