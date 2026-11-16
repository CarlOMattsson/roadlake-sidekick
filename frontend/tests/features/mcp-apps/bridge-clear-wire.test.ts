import { afterEach, expect, it, vi } from "vitest";
import {
  createHostBridge,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";

// An app empties a field with null; the tools/call that reaches the host names it in `clear`. Simulated host in jsdom,
// not a real Claude or Android host.

afterEach(() => {
  vi.restoreAllMocks();
});

type Sent = { id?: number; method?: string; params?: { arguments?: unknown } };

function hostMessage(data: object) {
  window.dispatchEvent(new MessageEvent("message", { data, source: window }));
}

async function sentArguments(name: string, args: object): Promise<unknown> {
  const sent: Sent[] = [];
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as Sent);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const ready = bridge.initialize();
  hostMessage({
    jsonrpc: "2.0",
    id: sent[0]!.id,
    result: { protocolVersion: MCP_APPS_PROTOCOL_VERSION, hostContext: {} },
  });
  await ready;
  const call = bridge.call(name, args);
  await vi.waitFor(() =>
    expect(sent.some((m) => m.method === "tools/call")).toBe(true),
  );
  const request = sent.find((m) => m.method === "tools/call")!;
  hostMessage({
    jsonrpc: "2.0",
    id: request.id,
    result: { structuredContent: {} },
  });
  await call;
  return request.params?.arguments;
}

it("sends a null in changes as a name in clear", async () => {
  expect(
    await sentArguments("update_task", {
      task_id: "t1",
      version: 2,
      changes: { due_at: null, title: "x" },
    }),
  ).toEqual({
    task_id: "t1",
    version: 2,
    changes: { title: "x" },
    clear: ["due_at"],
  });
});

it("leaves a call without a null untouched", async () => {
  const args = { task_id: "t1", version: 2, changes: { title: "x" } };
  expect(await sentArguments("update_task", args)).toEqual(args);
});
