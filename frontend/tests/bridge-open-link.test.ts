import { afterEach, expect, it, vi } from "vitest";
import {
  createHostBridge,
  isAllowedLinkUrl,
  MCP_APPS_PROTOCOL_VERSION,
} from "@/features/mcp-apps/bridge";

type Sent = {
  id?: number;
  method?: string;
  params?: { url?: string };
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

/** Anchors the bridge clicked as its new-tab fallback, without navigating jsdom. */
const clicked: { href: string; target: string; rel: string }[] = [];

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
  clicked.length = 0;
  vi.restoreAllMocks();
});

it("sends ui/open-link with the url when the host declares openLinks", async () => {
  const bridge = await bridgeWith({ openLinks: {} });
  const opening = bridge.openLink("https://example.com/kontakt");

  const request = lastOf("ui/open-link");
  expect(request?.params).toEqual({ url: "https://example.com/kontakt" });
  reply(request?.id, { result: {} });
  await expect(opening).resolves.toBe(true);
  expect(clicked).toHaveLength(0);
});

it("sends tel: and mailto: links to the host as well", async () => {
  const bridge = await bridgeWith({ openLinks: {} });
  const calling = bridge.openLink("tel:+46701740605");
  expect(lastOf("ui/open-link")?.params).toEqual({ url: "tel:+46701740605" });
  reply(lastOf("ui/open-link")?.id, { result: {} });
  await expect(calling).resolves.toBe(true);
});

it("opens a new tab through an anchor when the host declares no openLinks", async () => {
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push({
      href: this.href,
      target: this.target,
      rel: this.rel,
    });
  });
  const bridge = await bridgeWith({ message: {} });

  await expect(bridge.openLink("https://example.com/kontakt")).resolves.toBe(
    true,
  );

  expect(lastOf("ui/open-link")).toBeUndefined();
  expect(clicked).toHaveLength(1);
  expect(clicked[0]?.href).toBe("https://example.com/kontakt");
  expect(clicked[0]?.target).toBe("_blank");
  expect(clicked[0]?.rel).toContain("noopener");
});

it("refuses javascript: and sends nothing, with or without openLinks", async () => {
  const withCapability = await bridgeWith({ openLinks: {} });
  await expect(
    withCapability.openLink("javascript:alert(document.cookie)"),
  ).resolves.toBe(false);
  expect(lastOf("ui/open-link")).toBeUndefined();

  const withoutCapability = await bridgeWith({ message: {} });
  await expect(withoutCapability.openLink("javascript:alert(1)")).resolves.toBe(
    false,
  );
  expect(clicked).toHaveLength(0);
});

it("resolves false without a fallback when the host refuses the link", async () => {
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const bridge = await bridgeWith({ openLinks: {} });
  const opening = bridge.openLink("https://example.com/");
  reply(lastOf("ui/open-link")?.id, {
    error: { code: -32000, message: "Link denied" },
  });

  await expect(opening).resolves.toBe(false);
  expect(clickSpy).not.toHaveBeenCalled();
});

it("sends nothing before the handshake", async () => {
  vi.spyOn(window, "postMessage").mockImplementation((message: unknown) => {
    sent.push(message as Sent);
  });
  const early = createHostBridge({ name: "Test app", version: "1.0.0" });

  await expect(early.openLink("https://example.com/")).resolves.toBe(false);
  expect(lastOf("ui/open-link")).toBeUndefined();
});

it("allows only mailto:, tel: and https: links", () => {
  expect(isAllowedLinkUrl("https://example.com")).toBe(true);
  expect(isAllowedLinkUrl("mailto:anna@example.com")).toBe(true);
  expect(isAllowedLinkUrl("tel:+46701740605")).toBe(true);
  expect(isAllowedLinkUrl("javascript:alert(1)")).toBe(false);
  expect(isAllowedLinkUrl("http://example.com")).toBe(false);
  expect(isAllowedLinkUrl("data:text/html,hej")).toBe(false);
  expect(isAllowedLinkUrl("inte en url")).toBe(false);
  expect(isAllowedLinkUrl("")).toBe(false);
});
