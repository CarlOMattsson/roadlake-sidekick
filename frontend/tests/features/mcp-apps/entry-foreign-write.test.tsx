import { act, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

// A write the host reports for a call this app did not make (Claude moved Tasks) leaves no card, but the open view no
// longer shows what is stored: it reads again, quietly. A read result changes nothing. Simulated host (the bridge is
// mocked), not a real Claude host.

type Listener<T> = (value: T) => void;
type HostContext = {
  displayMode?: string;
  toolInfo?: { tool?: { name?: string } };
};

const host = vi.hoisted(() => ({
  toolResult: [] as Listener<{
    structuredContent: unknown;
    isError: boolean;
  }>[],
  hostContext: [] as Listener<HostContext>[],
  initialize: vi.fn(),
  call: vi.fn<
    (name: string, args: Record<string, unknown>) => Promise<unknown>
  >(),
}));

vi.mock("@/features/mcp-apps/bridge", () => ({
  createHostBridge: () => ({
    initialize: host.initialize,
    call: host.call,
    updateModelContext: vi.fn().mockResolvedValue(undefined),
    getFeatures: () => ({
      serverTools: true,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
    onToolInput: () => undefined,
    onToolCancelled: () => undefined,
    onToolResult: (listener: (typeof host.toolResult)[number]) => {
      host.toolResult.push(listener);
    },
    onHostContext: (listener: Listener<HostContext>) => {
      host.hostContext.push(listener);
    },
    onTeardown: () => undefined,
  }),
}));

const agenda = {
  items: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000a1",
      title: "Skicka offert",
      status: "todo",
      due_at: null,
      version: 1,
      agenda_group: "today",
    },
  ],
  next_cursor: null,
};

beforeAll(async () => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({
    locale: "en-GB",
    displayMode: "fullscreen",
    availableDisplayModes: ["inline", "fullscreen"],
  });
  host.call.mockImplementation((name) =>
    name === "get_work_agenda"
      ? Promise.resolve(agenda)
      : new Promise(() => undefined),
  );
  await import("@/features/mcp-apps/sidekick-entry");
});

afterAll(() => {
  document.head.innerHTML = "";
});

/** What a host sends when a tool call ends: its context names the tool, then the result follows. */
function result(tool: string, structuredContent: unknown) {
  act(() => {
    for (const listener of host.hostContext)
      listener({
        displayMode: "fullscreen",
        toolInfo: { tool: { name: tool } },
      });
    for (const listener of host.toolResult)
      listener({ structuredContent, isError: false });
  });
}

const agendaReads = () =>
  host.call.mock.calls.filter(([name]) => name === "get_work_agenda").length;

describe("entry, a write result for a call the app did not make", () => {
  it("reads the open agenda again for reschedule_tasks, and not for a read", async () => {
    result("get_work_agenda", agenda);
    expect(await screen.findByText("Skicka offert")).toBeInTheDocument();
    const before = agendaReads();

    // A read of something else leaves the open agenda as it is.
    result("get_today_brief", { day: "2026-11-18" });
    await act(() => Promise.resolve());
    expect(agendaReads()).toBe(before);

    result("reschedule_tasks", { count: 3, tasks: [] });
    await vi.waitFor(() => expect(agendaReads()).toBe(before + 1));
    expect(screen.getByText("Skicka offert")).toBeInTheDocument();
  });
});
