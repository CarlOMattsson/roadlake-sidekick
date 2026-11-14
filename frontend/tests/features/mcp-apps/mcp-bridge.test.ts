import { afterEach, expect, it, vi } from "vitest";
import {
  createHostBridge,
  isSupportedProtocolVersion,
  MCP_APPS_PROTOCOL_VERSION,
  MIN_SUPPORTED_PROTOCOL,
} from "@/features/mcp-apps/bridge";

type SentMessage = {
  id?: number;
  method?: string;
  params?: {
    protocolVersion?: string;
    mode?: string;
    appCapabilities?: { availableDisplayModes?: string[] };
    content?: { type: string; text: string }[];
    width?: number;
    height?: number;
  };
};

const sent: SentMessage[] = [];

function answerRequest(
  method: string,
  body: { result: unknown } | { error: unknown },
) {
  const request = sent.find((message) => message.method === method);
  if (request?.id === undefined) throw new Error(`${method} was not sent`);
  const event = new MessageEvent("message", {
    data: { jsonrpc: "2.0", id: request.id, ...body },
    source: window,
  });
  window.dispatchEvent(event);
}

/** requestDisplayMode waits for the handshake before posting, so the request may land a tick later. */
async function waitForRequest(method: string) {
  await vi.waitFor(() => {
    if (!sent.some((message) => message.method === method))
      throw new Error(`${method} not sent yet`);
  });
}

function answerInitialize(
  protocolVersion: unknown,
  hostContext: object = { theme: "light" },
) {
  answerRequest("ui/initialize", {
    result: { protocolVersion, hostContext },
  });
}

function initializeWith(protocolVersion: unknown, hostContext?: object) {
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  answerInitialize(protocolVersion, hostContext);
  return initialized;
}

afterEach(() => {
  sent.length = 0;
  vi.restoreAllMocks();
});

it("keeps sending the app's own protocol version in ui/initialize", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });

  await initializeWith(MCP_APPS_PROTOCOL_VERSION);

  const request = sent.find((message) => message.method === "ui/initialize");
  expect(request?.params?.protocolVersion).toBe(MCP_APPS_PROTOCOL_VERSION);
});

it("accepts a host answering with the same protocol version", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });

  await expect(initializeWith("2026-01-26")).resolves.toEqual({
    theme: "light",
  });
});

it("accepts a host answering with a newer protocol version", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });

  await expect(initializeWith("2026-06-01")).resolves.toEqual({
    theme: "light",
  });
  sent.length = 0;
  await expect(initializeWith("2027-01-01")).resolves.toEqual({
    theme: "light",
  });
});

it("refuses a host answering with a version older than the minimum", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });

  await expect(initializeWith("2026-01-25")).rejects.toThrow(
    "Unsupported protocol",
  );
});

it("refuses a host answer without a usable protocol version", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });

  await expect(initializeWith(undefined)).rejects.toThrow(
    "Unsupported protocol",
  );
  sent.length = 0;
  await expect(initializeWith("2026-1-26")).rejects.toThrow(
    "Unsupported protocol",
  );
});

it("orders protocol versions as ISO dates against the minimum", () => {
  expect(MIN_SUPPORTED_PROTOCOL).toBe("2026-01-26");
  expect(isSupportedProtocolVersion("2026-01-26")).toBe(true);
  expect(isSupportedProtocolVersion("2026-01-27")).toBe(true);
  expect(isSupportedProtocolVersion("2026-02-01")).toBe(true);
  expect(isSupportedProtocolVersion("2026-01-25")).toBe(false);
  expect(isSupportedProtocolVersion("2025-12-31")).toBe(false);
  expect(isSupportedProtocolVersion("")).toBe(false);
  expect(isSupportedProtocolVersion("latest")).toBe(false);
  expect(isSupportedProtocolVersion(20260126)).toBe(false);
  expect(isSupportedProtocolVersion(undefined)).toBe(false);
});

it("declares inline and fullscreen as the app's display modes in ui/initialize", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });

  await initializeWith(MCP_APPS_PROTOCOL_VERSION);

  const request = sent.find((message) => message.method === "ui/initialize");
  expect(request?.params?.appCapabilities).toEqual({
    availableDisplayModes: ["inline", "fullscreen"],
  });
});

it("returns the display mode and host context fields from ui/initialize", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const hostContext = {
    theme: "dark",
    displayMode: "inline",
    availableDisplayModes: ["inline", "fullscreen"],
    safeAreaInsets: { top: 0, right: 0, bottom: 34, left: 0 },
    platform: "mobile",
  };

  await expect(
    initializeWith(MCP_APPS_PROTOCOL_VERSION, hostContext),
  ).resolves.toEqual(hostContext);
});

it("sends ui/request-display-mode and resolves the mode the host actually set", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  answerInitialize(MCP_APPS_PROTOCOL_VERSION);
  await initialized;

  const requested = bridge.requestDisplayMode("fullscreen");
  await waitForRequest("ui/request-display-mode");
  const request = sent.find(
    (message) => message.method === "ui/request-display-mode",
  );
  expect(request?.params).toEqual({ mode: "fullscreen" });
  // The host declines the switch and stays inline; the bridge reports that instead of the request.
  answerRequest("ui/request-display-mode", { result: { mode: "inline" } });

  await expect(requested).resolves.toBe("inline");
});

it("rejects when the host errors on ui/request-display-mode or answers an unknown mode", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  answerInitialize(MCP_APPS_PROTOCOL_VERSION);
  await initialized;

  const failed = bridge.requestDisplayMode("fullscreen");
  await waitForRequest("ui/request-display-mode");
  answerRequest("ui/request-display-mode", { error: { code: -32000 } });
  await expect(failed).rejects.toThrow("Host request failed");

  sent.length = 0;
  const unknown = bridge.requestDisplayMode("pip");
  await waitForRequest("ui/request-display-mode");
  answerRequest("ui/request-display-mode", { result: { mode: "floating" } });
  await expect(unknown).rejects.toThrow("Unsupported display mode");
});

it("passes displayMode from host-context-changed to listeners", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  answerInitialize(MCP_APPS_PROTOCOL_VERSION);
  await initialized;
  const listener = vi.fn();
  bridge.onHostContext(listener);

  window.dispatchEvent(
    new MessageEvent("message", {
      data: {
        jsonrpc: "2.0",
        method: "ui/notifications/host-context-changed",
        params: { displayMode: "fullscreen" },
      },
      source: window,
    }),
  );

  // The listener gets the merged context (the initialize theme plus the new displayMode).
  expect(listener).toHaveBeenCalledWith(
    expect.objectContaining({ displayMode: "fullscreen" }),
  );
});

async function initializedBridge() {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  answerInitialize(MCP_APPS_PROTOCOL_VERSION);
  await initialized;
  sent.length = 0;
  return bridge;
}

function contextMessages() {
  return sent.filter((message) => message.method === "ui/update-model-context");
}

it("sends ui/update-model-context with the summary as a text block when the host accepts", async () => {
  const bridge = await initializedBridge();

  const updated = bridge.updateModelContext("Flyttade uppgift 7 till Klar");
  await waitForRequest("ui/update-model-context");
  expect(contextMessages()[0]?.params).toEqual({
    content: [{ type: "text", text: "Flyttade uppgift 7 till Klar" }],
  });
  answerRequest("ui/update-model-context", { result: {} });

  await expect(updated).resolves.toBeUndefined();
});

it("is a silent no-op when the host refuses or fails the update", async () => {
  const bridge = await initializedBridge();

  const refused = bridge.updateModelContext("Flyttade uppgift 7 till Klar");
  await waitForRequest("ui/update-model-context");
  answerRequest("ui/update-model-context", {
    error: { code: -32601, message: "Method not found" },
  });

  await expect(refused).resolves.toBeUndefined();
});

it("sends nothing before the handshake or after teardown", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });

  await expect(
    bridge.updateModelContext("Flyttade uppgift 7 till Klar"),
  ).resolves.toBeUndefined();
  expect(contextMessages()).toHaveLength(0);

  const initialized = bridge.initialize();
  answerInitialize(MCP_APPS_PROTOCOL_VERSION);
  await initialized;
  sent.length = 0;
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { jsonrpc: "2.0", method: "ui/resource-teardown" },
      source: window,
    }),
  );
  await expect(
    bridge.updateModelContext("Flyttade uppgift 7 till Klar"),
  ).resolves.toBeUndefined();
  expect(contextMessages()).toHaveLength(0);
});

it("caps the summary at 500 characters and drops empty summaries", async () => {
  const bridge = await initializedBridge();

  const long = bridge.updateModelContext("a".repeat(600));
  await waitForRequest("ui/update-model-context");
  const content = contextMessages()[0]?.params?.content as
    { text: string }[] | undefined;
  expect(content?.[0]?.text).toHaveLength(500);
  answerRequest("ui/update-model-context", { result: {} });
  await long;

  await bridge.updateModelContext("   ");
  expect(contextMessages()).toHaveLength(1);
});

it("skips an identical summary sent again within the debounce window", async () => {
  const realNow = Date.now();
  vi.useFakeTimers({ toFake: ["Date"] });
  try {
    vi.setSystemTime(realNow);
    const bridge = await initializedBridge();
    const first = bridge.updateModelContext("Flyttade uppgift 7 till Klar");
    await bridge.updateModelContext("Flyttade uppgift 7 till Klar");
    expect(contextMessages()).toHaveLength(1);
    answerRequest("ui/update-model-context", { result: {} });
    await first;

    vi.setSystemTime(realNow + 2_001);
    const later = bridge.updateModelContext("Flyttade uppgift 7 till Klar");
    const latest = contextMessages().at(-1);
    expect(contextMessages()).toHaveLength(2);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { jsonrpc: "2.0", id: latest?.id, result: {} },
        source: window,
      }),
    );
    await later;
  } finally {
    vi.useRealTimers();
  }
});

async function bridgeInitializedWith(hostContext: object) {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as SentMessage);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  answerInitialize(MCP_APPS_PROTOCOL_VERSION, hostContext);
  await initialized;
  sent.length = 0;
  return bridge;
}

function dispatchHostMessage(method: string, params: object) {
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { jsonrpc: "2.0", method, params },
      source: window,
    }),
  );
}

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
});

it("applies styles, theme and safe area from the ui/initialize answer", async () => {
  await bridgeInitializedWith({
    theme: "dark",
    styles: { variables: { "--color-test-accent": "#123456" } },
    safeAreaInsets: { top: 0, right: 0, bottom: 34, left: 0 },
  });

  const root = document.documentElement;
  expect(root.getAttribute("data-theme")).toBe("dark");
  expect(root.style.colorScheme).toBe("dark");
  expect(root.style.getPropertyValue("--color-test-accent")).toBe("#123456");
  expect(root.style.getPropertyValue("--host-safe-bottom")).toBe("34px");
});

it("re-applies host style on host-context-changed", async () => {
  await bridgeInitializedWith({ theme: "light" });

  dispatchHostMessage("ui/notifications/host-context-changed", {
    theme: "dark",
  });

  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  expect(document.documentElement.style.colorScheme).toBe("dark");
});

it("merges partial host-context-changed updates into the context given to listeners", async () => {
  const bridge = await bridgeInitializedWith({
    theme: "light",
    locale: "sv-SE",
  });
  const listener = vi.fn();
  bridge.onHostContext(listener);

  dispatchHostMessage("ui/notifications/host-context-changed", {
    displayMode: "fullscreen",
  });
  expect(listener).toHaveBeenLastCalledWith({
    theme: "light",
    locale: "sv-SE",
    displayMode: "fullscreen",
  });

  dispatchHostMessage("ui/notifications/host-context-changed", {
    theme: "dark",
  });
  expect(listener).toHaveBeenLastCalledWith({
    theme: "dark",
    locale: "sv-SE",
    displayMode: "fullscreen",
  });
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
});

it.each([
  ["timeZone", "Europe/Stockholm"],
  ["styles", { variables: { "--color-test-accent": "#123456" } }],
  ["deviceCapabilities", { touch: true, hover: false }],
  ["toolInfo", { id: "tool-1", tool: { name: "get_task" } }],
])("passes %s from host-context-changed to listeners", async (field, value) => {
  const bridge = await bridgeInitializedWith({ theme: "light" });
  const listener = vi.fn();
  bridge.onHostContext(listener);

  dispatchHostMessage("ui/notifications/host-context-changed", {
    [field]: value,
  });

  expect(listener).toHaveBeenLastCalledWith(
    expect.objectContaining({ [field]: value }),
  );
});

it("passes tool-input arguments to onToolInput listeners", async () => {
  const bridge = await bridgeInitializedWith({});
  const listener = vi.fn();
  bridge.onToolInput(listener);

  dispatchHostMessage("ui/notifications/tool-input", {
    arguments: { id: 7 },
  });

  expect(listener).toHaveBeenCalledWith({ id: 7 });
});

it("passes an empty input to onToolInput when the arguments are not an object", async () => {
  const bridge = await bridgeInitializedWith({});
  const listener = vi.fn();
  bridge.onToolInput(listener);

  dispatchHostMessage("ui/notifications/tool-input", { arguments: "7" });

  expect(listener).toHaveBeenCalledWith({});
});

it("passes the cancel reason to onToolCancelled listeners", async () => {
  const bridge = await bridgeInitializedWith({});
  const listener = vi.fn();
  bridge.onToolCancelled(listener);

  dispatchHostMessage("ui/notifications/tool-cancelled", {
    reason: "timeout",
  });

  expect(listener).toHaveBeenCalledWith({ reason: "timeout" });
});

it("drops a cancel reason that is not a string", async () => {
  const bridge = await bridgeInitializedWith({});
  const listener = vi.fn();
  bridge.onToolCancelled(listener);

  dispatchHostMessage("ui/notifications/tool-cancelled", { reason: 42 });

  expect(listener).toHaveBeenCalledWith({});
});

it("sends size-changed with width and height only when the body size changes", async () => {
  const resize: { notify?: () => void } = {};
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize.notify = callback;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  try {
    const rect = vi
      .spyOn(document.body, "getBoundingClientRect")
      .mockReturnValue({ width: 320, height: 480 } as DOMRect);
    await bridgeInitializedWith({});
    const sizes = () =>
      sent
        .filter((message) => message.method === "ui/notifications/size-changed")
        .map((message) => message.params);

    resize.notify?.();
    expect(sizes()).toEqual([{ width: 320, height: 480 }]);

    resize.notify?.();
    expect(sizes()).toHaveLength(1);

    rect.mockReturnValue({ width: 400, height: 480 } as DOMRect);
    resize.notify?.();
    expect(sizes()).toEqual([
      { width: 320, height: 480 },
      { width: 400, height: 480 },
    ]);
  } finally {
    vi.unstubAllGlobals();
  }
});
