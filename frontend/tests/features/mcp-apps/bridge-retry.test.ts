import { afterEach, expect, it, vi } from "vitest";
import {
  createHostBridge,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";

// A failed ui/initialize can be tried again: the start-up error card's "Försök igen" runs the handshake a
// second time, and commands then wait for that attempt instead of the one that failed.

afterEach(() => {
  vi.restoreAllMocks();
});

type Sent = { id?: number; method?: string };

function hostMessage(data: object) {
  window.dispatchEvent(new MessageEvent("message", { data, source: window }));
}

it("can run the handshake again after a failed one, and commands then work", async () => {
  const sent: Sent[] = [];
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as Sent);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });

  const first = bridge.initialize();
  hostMessage({
    jsonrpc: "2.0",
    id: sent[0]!.id,
    error: { code: -32000, message: "no" },
  });
  await expect(first).rejects.toBeDefined();

  const second = bridge.initialize();
  const handshakes = sent.filter((m) => m.method === "ui/initialize");
  expect(handshakes).toHaveLength(2);
  hostMessage({
    jsonrpc: "2.0",
    id: handshakes[1]!.id,
    result: { protocolVersion: MCP_APPS_PROTOCOL_VERSION, hostContext: {} },
  });
  await expect(second).resolves.toEqual({});

  const call = bridge.call("anything", {});
  await vi.waitFor(() =>
    expect(sent.some((m) => m.method === "tools/call")).toBe(true),
  );
  hostMessage({
    jsonrpc: "2.0",
    id: sent.find((m) => m.method === "tools/call")!.id,
    result: { structuredContent: { ok: true } },
  });
  await expect(call).resolves.toEqual({ ok: true });
});
