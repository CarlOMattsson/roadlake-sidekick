import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { preloadSidekickApp } from "./helpers/preload-sidekick-app";

type ToolResultListener = (result: {
  structuredContent: unknown;
  isError: boolean;
}) => void;

// Swedish inline agenda card through the Sidekick app entry. The app reads its language once, when
// sidekick-entry is imported, so the Swedish Sidekick setting needs its own test file and import.
// The bridge is the only thing mocked: sidekick-entry runs at import time and binds its listeners here.
const host = vi.hoisted(() => ({
  toolResult: [] as ToolResultListener[],
  initialize: vi.fn(),
  call: vi.fn(),
  requestDisplayMode: vi.fn(),
  updateModelContext: vi.fn(),
}));

vi.mock("@/features/mcp-apps/bridge", () => ({
  createHostBridge: () => ({
    initialize: host.initialize,
    call: host.call,
    requestDisplayMode: host.requestDisplayMode,
    updateModelContext: host.updateModelContext,
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

const agenda = {
  items: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000b1",
      title: "Betala faktura",
      status: "todo",
      due_at: "2026-10-20T09:00:00Z",
      agenda_group: "overdue",
    },
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000b2",
      title: "Städa garaget",
      status: "todo",
      due_at: "2026-11-02T09:00:00Z",
      agenda_group: "upcoming",
    },
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000b3",
      title: "Ring Anna",
      status: "todo",
      due_at: "2026-11-03T09:00:00Z",
      agenda_group: "upcoming",
    },
  ],
  next_cursor: null,
};

/** Delivers a tool result to every listener the app registered, as the host would. */
function deliver(structuredContent: unknown, isError = false) {
  act(() => {
    for (const listener of host.toolResult)
      listener({ structuredContent, isError });
  });
}

// The app's modules load at collection time, which has no timeout; the entry import in beforeAll then only
// runs the entry itself.
await preloadSidekickApp();

afterAll(() => {
  document.head.innerHTML = "";
});

beforeAll(async () => {
  // The Sidekick setting is declared explicitly; the host's en-GB locale must not change it.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="sv">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    availableDisplayModes: ["inline", "fullscreen"],
  });
  host.requestDisplayMode.mockResolvedValue({ displayMode: "fullscreen" });
  await import("@/features/mcp-apps/sidekick-entry");
  // Initialize resolves on a microtask; until the first tool result the app shows the awaiting skeleton.
  await waitFor(() =>
    expect(
      document.querySelector('[role="status"][aria-busy="true"]'),
    ).not.toBeNull(),
  );
});

describe("inline agenda card in Swedish", () => {
  it("shows the Swedish title with the Open button (foot counting the two upcoming rows), lists the overdue record under no heading, and a press on Open asks for fullscreen", async () => {
    const user = userEvent.setup();
    deliver(agenda);

    expect(screen.getByRole("region", { name: "Agenda" })).toBeInTheDocument();
    // The kicker is the app name and today's date; the title counts the overdue and today records.
    expect(screen.getByText(/^Arbete · /)).toBeInTheDocument();
    expect(screen.getByText("1 försenad")).toBeInTheDocument();
    expect(screen.getByText("Betala faktura")).toBeInTheDocument();
    expect(screen.queryByText("Börja med")).toBeNull();
    // The Open button is "Öppna Agenda" and its foot counts the page's rows the card leaves out: 3 rows, 1 shown.
    expect(
      screen.getAllByRole("button", {
        name: /^Öppna Agenda/,
      }),
    ).toHaveLength(1);
    expect(screen.getByText("· 2 fler")).toHaveClass("work-compact-more");

    await user.click(
      screen.getByRole("button", {
        name: /^Öppna Agenda/,
      }),
    );
    expect(host.requestDisplayMode).toHaveBeenCalledWith("fullscreen");
  });

  it("does not list the upcoming records inline", () => {
    deliver(agenda);
    expect(screen.queryByText("Städa garaget")).toBeNull();
    expect(screen.queryByText("Ring Anna")).toBeNull();
  });
});
