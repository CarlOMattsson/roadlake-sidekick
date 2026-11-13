import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

// The entry hands the room the tool and record id of a failed call, so the card's heading names the record and Try
// again reads it. An error that names no known tool does not inherit the view the card was on. Simulated host (the
// bridge is mocked), not a real Claude host.

type Listener<T> = (value: T) => void;

const host = vi.hoisted(() => ({
  toolInput: [] as Listener<Record<string, unknown>>[],
  toolResult: [] as Listener<{
    structuredContent: unknown;
    isError: boolean;
  }>[],
  toolCancelled: [] as Listener<{ reason?: string }>[],
  hostContext: [] as Listener<{ toolInfo?: { tool?: { name?: string } } }>[],
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
      serverTools: false,
      message: false,
      openLinks: false,
    }),
    sendMessage: vi.fn().mockResolvedValue(false),
    onToolInput: (listener: Listener<Record<string, unknown>>) => {
      host.toolInput.push(listener);
    },
    onToolCancelled: (listener: Listener<{ reason?: string }>) => {
      host.toolCancelled.push(listener);
    },
    onToolResult: (listener: (typeof host.toolResult)[number]) => {
      host.toolResult.push(listener);
    },
    onHostContext: (listener: (typeof host.hostContext)[number]) => {
      host.hostContext.push(listener);
    },
    onTeardown: () => undefined,
  }),
}));

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const task = {
  id: TASK_ID,
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};

beforeAll(async () => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  document.body.innerHTML = '<div id="root"></div>';
  host.initialize.mockResolvedValue({ locale: "en-GB" });
  await import("@/features/mcp-apps/sidekick-entry");
});

afterAll(() => {
  document.head.innerHTML = "";
});

/** What a host sends for a failed tool call: the tool input, then the error result (the tool name is optional). */
function fail(tool: string | undefined, input?: Record<string, unknown>) {
  act(() => {
    for (const listener of host.hostContext)
      listener({
        toolInfo: tool === undefined ? undefined : { tool: { name: tool } },
      });
    if (input) for (const listener of host.toolInput) listener(input);
    for (const listener of host.toolResult)
      listener({ structuredContent: undefined, isError: true });
  });
}

describe("entry, a failed tool call", () => {
  it("names the Task the call read, and Try again reads that Task", async () => {
    host.call.mockImplementation((name) =>
      name === "get_task"
        ? Promise.resolve({ task })
        : new Promise(() => undefined),
    );
    fail("get_task", { task_id: TASK_ID });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load the task",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(task.title)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(host.call).toHaveBeenCalledWith("get_task", { task_id: TASK_ID });
  });

  it("does not let an error without a tool inherit the view of the card, so it reads the agenda", async () => {
    host.call.mockReset();
    host.call.mockImplementation((name) =>
      name === "get_work_agenda"
        ? Promise.resolve({ items: [], next_cursor: null })
        : new Promise(() => undefined),
    );
    // The card first failed as a Projects read; a later error names no tool.
    fail("get_work_hierarchy");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load your projects",
    );
    fail(undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load your tasks",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() =>
      expect(host.call).toHaveBeenCalledWith(
        "get_work_agenda",
        expect.anything(),
      ),
    );
    expect(host.call).not.toHaveBeenCalledWith(
      "get_work_hierarchy",
      expect.anything(),
    );
  });

  it("drops the input of a cancelled call, so a later error names no record", async () => {
    host.call.mockReset();
    host.call.mockImplementation((name) =>
      name === "get_work_agenda"
        ? Promise.resolve({ items: [], next_cursor: null })
        : new Promise(() => undefined),
    );
    act(() => {
      for (const listener of host.toolInput) listener({ task_id: TASK_ID });
      for (const listener of host.toolCancelled) listener({});
    });
    fail("get_task");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn’t load your tasks",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() =>
      expect(host.call).toHaveBeenCalledWith(
        "get_work_agenda",
        expect.anything(),
      ),
    );
    expect(host.call).not.toHaveBeenCalledWith("get_task", expect.anything());
  });
});
