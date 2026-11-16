import { afterEach, expect, it, vi } from "vitest";
import {
  createHostBridge,
  HostToolError,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";
import { errorCode, errorReason } from "@/lib/mcp/errors";

// A refused tools/call carries the server's closed code and closed reason, and nothing of its text. Simulated host in
// jsdom, not a real Claude or Android host.

afterEach(() => {
  vi.restoreAllMocks();
});

type Sent = { id?: number; method?: string };

function hostMessage(data: object) {
  window.dispatchEvent(new MessageEvent("message", { data, source: window }));
}

async function refusedWith(structuredContent: object): Promise<unknown> {
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
  const call = bridge.call("run_ai_plan", {});
  await vi.waitFor(() =>
    expect(sent.some((m) => m.method === "tools/call")).toBe(true),
  );
  hostMessage({
    jsonrpc: "2.0",
    id: sent.find((m) => m.method === "tools/call")!.id,
    result: { isError: true, structuredContent },
  });
  return call.then(
    () => undefined,
    (error: unknown) => error,
  );
}

it("keeps the closed code and reason of a refusal, not its text", async () => {
  const error = await refusedWith({
    code: "conflict",
    reason: "ai_budget_reached",
    message: "a spending cap would be passed",
  });
  expect(error).toBeInstanceOf(HostToolError);
  expect(errorCode(error)).toBe("conflict");
  expect(errorReason(error)).toBe("ai_budget_reached");
  expect((error as Error).message).toBe("Tool request failed");
});

it("drops a reason that is not a short string", async () => {
  const long = await refusedWith({ code: "conflict", reason: "x".repeat(65) });
  expect(errorReason(long)).toBeUndefined();
  const odd = await refusedWith({ code: "conflict", reason: 7 });
  expect(errorReason(odd)).toBeUndefined();
});
