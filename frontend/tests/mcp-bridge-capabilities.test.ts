import { afterEach, expect, it, vi } from "vitest";
import {
  createHostBridge,
  featuresFrom,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";

type Sent = {
  id?: number;
  method?: string;
  params?: { role?: string; content?: { type?: string; text?: string } };
};
const sent: Sent[] = [];

function reply(id: number | undefined, body: object) {
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { jsonrpc: "2.0", id, ...body },
      source: window,
    }),
  );
}
function lastOf(method: string) {
  return sent.filter((message) => message.method === method).at(-1);
}

async function bridgeWith(hostCapabilities?: unknown) {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as Sent);
  });
  const bridge = createHostBridge({ name: "Test app", version: "1.0.0" });
  const initialized = bridge.initialize();
  reply(lastOf("ui/initialize")?.id, {
    result: {
      protocolVersion: MCP_APPS_PROTOCOL_VERSION,
      hostContext: {},
      ...(hostCapabilities === undefined ? {} : { hostCapabilities }),
    },
  });
  await initialized;
  sent.length = 0;
  return bridge;
}

afterEach(() => {
  sent.length = 0;
  vi.restoreAllMocks();
});

it("reads serverTools, message and openLinks from hostCapabilities", async () => {
  const bridge = await bridgeWith({ serverTools: {}, openLinks: {} });
  expect(bridge.getFeatures()).toEqual({
    serverTools: true,
    message: false,
    openLinks: true,
  });
});

it("assumes every feature when the host declares no capabilities", async () => {
  const bridge = await bridgeWith();
  expect(bridge.getFeatures()).toEqual({
    serverTools: true,
    message: true,
    openLinks: true,
  });
  expect(featuresFrom("junk")).toEqual(featuresFrom(undefined));
  expect(featuresFrom(null).serverTools).toBe(true);
});

it("believes a declared object: a missing key means a missing feature", () => {
  expect(featuresFrom({})).toEqual({
    serverTools: false,
    message: false,
    openLinks: false,
  });
  expect(featuresFrom({ message: { text: {} } }).message).toBe(true);
  expect(featuresFrom({ serverTools: "yes" }).serverTools).toBe(false);
});

it("sends ui/message as a user text and resolves true when the host accepts", async () => {
  const bridge = await bridgeWith({ message: { text: {} } });
  const sending = bridge.sendMessage("Öppna Dagbok");
  const request = lastOf("ui/message");
  expect(request?.params).toEqual({
    role: "user",
    content: { type: "text", text: "Öppna Dagbok" },
  });
  reply(request?.id, { result: {} });
  await expect(sending).resolves.toBe(true);
});

it("resolves false without throwing when the host refuses or fails", async () => {
  const bridge = await bridgeWith({ message: {} });
  const sending = bridge.sendMessage("Öppna Dagbok");
  reply(lastOf("ui/message")?.id, {
    error: { code: -32000, message: "Message sending denied" },
  });
  await expect(sending).resolves.toBe(false);
});

it("sends nothing when the host declared capabilities without message", async () => {
  const bridge = await bridgeWith({ serverTools: {} });
  await expect(bridge.sendMessage("Öppna Dagbok")).resolves.toBe(false);
  expect(lastOf("ui/message")).toBeUndefined();
});

it("sends nothing before the handshake or after teardown, and drops empty text", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as Sent);
  });
  const early = createHostBridge({ name: "Test app", version: "1.0.0" });
  await expect(early.sendMessage("Öppna Arbete")).resolves.toBe(false);
  expect(lastOf("ui/message")).toBeUndefined();
  vi.restoreAllMocks();

  const bridge = await bridgeWith({ message: {} });
  await expect(bridge.sendMessage("   ")).resolves.toBe(false);
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { jsonrpc: "2.0", method: "ui/resource-teardown" },
      source: window,
    }),
  );
  await expect(bridge.sendMessage("Öppna Arbete")).resolves.toBe(false);
  expect(lastOf("ui/message")).toBeUndefined();
});

it("caps the text at 500 characters and skips an identical text within 2 seconds", async () => {
  const realNow = Date.now();
  vi.useFakeTimers({ toFake: ["Date"] });
  try {
    vi.setSystemTime(realNow);
    const bridge = await bridgeWith({ message: {} });
    const first = bridge.sendMessage("a".repeat(600));
    expect(lastOf("ui/message")?.params?.content?.text).toHaveLength(500);
    const repeat = bridge.sendMessage("a".repeat(600));
    await expect(repeat).resolves.toBe(false);
    expect(sent.filter((m) => m.method === "ui/message")).toHaveLength(1);
    reply(lastOf("ui/message")?.id, { result: {} });
    await expect(first).resolves.toBe(true);
  } finally {
    vi.useRealTimers();
  }
});
