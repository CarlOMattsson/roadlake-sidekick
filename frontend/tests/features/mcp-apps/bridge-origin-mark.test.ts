import { afterEach, expect, it, vi } from "vitest";
import {
  APP_ORIGIN_META,
  createHostBridge,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";

type Sent = { id?: number; method?: string; params?: Record<string, unknown> };
const sent: Sent[] = [];

function reply(id: number | undefined, body: object) {
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { jsonrpc: "2.0", id, ...body },
      source: window,
    }),
  );
}

afterEach(() => {
  sent.length = 0;
  vi.restoreAllMocks();
});

it("marks every tools/call as the app's own, so the history says 'you'", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as Sent);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  reply(sent.find((m) => m.method === "ui/initialize")?.id, {
    result: { protocolVersion: MCP_APPS_PROTOCOL_VERSION, hostContext: {} },
  });
  await initialized;
  sent.length = 0;

  const calling = bridge.call("move_to_trash", { id: "1" });
  await vi.waitFor(() =>
    expect(sent.some((m) => m.method === "tools/call")).toBe(true),
  );
  const request = sent.find((m) => m.method === "tools/call");
  expect(request?.params?.name).toBe("move_to_trash");
  expect(request?.params?._meta).toEqual(APP_ORIGIN_META);
  expect(APP_ORIGIN_META).toEqual({ "com.roadlake.sidekick/origin": "app" });
  reply(request?.id, { result: { structuredContent: {}, isError: false } });
  await calling;
});
