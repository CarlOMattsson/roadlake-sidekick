import { afterEach, expect, it, vi } from "vitest";
import { createHostBridge } from "@/features/mcp-apps/bridge";

// The bridge listens to window messages from creation until ui/resource-teardown. After teardown the
// listener must be removed, not just ignored.

afterEach(() => {
  vi.restoreAllMocks();
});

function hostMessage(data: object) {
  window.dispatchEvent(new MessageEvent("message", { data, source: window }));
}

it("removes its window message listener on ui/resource-teardown", () => {
  const add = vi.spyOn(window, "addEventListener");
  const remove = vi.spyOn(window, "removeEventListener");
  createHostBridge({ name: "Test app", version: "1.0.0" });

  const messageListeners = add.mock.calls
    .filter(([type]) => type === "message")
    .map(([, listener]) => listener);
  expect(messageListeners).toHaveLength(1);
  expect(remove).not.toHaveBeenCalledWith("message", messageListeners[0]);

  hostMessage({ jsonrpc: "2.0", method: "ui/resource-teardown" });

  expect(remove).toHaveBeenCalledWith("message", messageListeners[0]);
});

it("delivers host notifications until teardown and none after it", () => {
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const onToolResult = vi.fn();
  bridge.onToolResult(onToolResult);
  const notification = {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: { structuredContent: { ok: true } },
  };

  hostMessage(notification);
  expect(onToolResult).toHaveBeenCalledTimes(1);

  hostMessage({ jsonrpc: "2.0", method: "ui/resource-teardown" });
  hostMessage(notification);
  expect(onToolResult).toHaveBeenCalledTimes(1);
});
