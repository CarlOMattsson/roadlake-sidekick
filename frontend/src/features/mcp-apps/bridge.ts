import { applyHostStyle } from "@/features/mcp-apps/host-style";

/**
 * MCP Apps 2026-01-26 host bridge shared by every Sidekick App resource.
 * No network, credential or backend URL: the only channel is postMessage to the host.
 */
export const MCP_APPS_PROTOCOL_VERSION = "2026-01-26";
/**
 * Oldest host protocol version this bridge accepts. A host answering with this version or
 * any newer ISO-date version is accepted; anything older is refused.
 */
export const MIN_SUPPORTED_PROTOCOL = "2026-01-26";

const PROTOCOL_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Versions are ISO dates, so lexicographic order is chronological order. A missing or
 * malformed host version cannot be ordered against the minimum and is refused.
 */
export function isSupportedProtocolVersion(version: unknown): boolean {
  return (
    typeof version === "string" &&
    PROTOCOL_DATE.test(version) &&
    version >= MIN_SUPPORTED_PROTOCOL
  );
}

/** MCP Apps display modes ("Display Modes"). */
export type DisplayMode = "inline" | "fullscreen" | "pip";
const DISPLAY_MODES: readonly string[] = ["inline", "fullscreen", "pip"];
/** Display modes this app declares in ui/initialize; a host may only switch within these. */
const APP_DISPLAY_MODES: DisplayMode[] = ["inline", "fullscreen"];

/**
 * Host context as the bridge holds it: the ui/initialize answer merged with every later
 * host-context-changed. Every field is optional and untrusted; consumers check before use.
 */
export type HostContext = {
  locale?: string;
  /** IANA time zone name reported by the host. */
  timeZone?: string;
  theme?: string;
  /** Host style; `variables` are CSS custom properties applied by applyHostStyle. */
  styles?: { variables?: Record<string, unknown> };
  /** How the app is currently displayed. */
  displayMode?: DisplayMode;
  /** Display modes the host supports; check before calling requestDisplayMode. */
  availableDisplayModes?: string[];
  /** Safe area boundaries in pixels. */
  safeAreaInsets?: { top: number; right: number; bottom: number; left: number };
  platform?: "web" | "desktop" | "mobile";
  /** Input capabilities of the device; a missing flag means the host did not report it. */
  deviceCapabilities?: { touch?: boolean; hover?: boolean };
  /** The tool call that opened the app. `id` is absent on some hosts (iOS rehydration). */
  toolInfo?: { id?: string | number; tool?: { name?: string } };
};
/**
 * What the host says it supports, as sent in the ui/initialize answer (`hostCapabilities`).
 * Only the three keys the bridge acts on are typed; every key is optional and untrusted.
 */
export type HostCapabilities = {
  /** The host can proxy tools/call to the MCP server. */
  serverTools?: object;
  /** The host accepts ui/message (draft spec; the 2026-01-26 spec has no such flag). */
  message?: object;
  /** The host can open external links. */
  openLinks?: object;
};
/** The capabilities the app acts on, as plain booleans. */
export type HostFeatures = {
  serverTools: boolean;
  message: boolean;
  openLinks: boolean;
};
/**
 * Reads the booleans from a host answer. A host that sends no `hostCapabilities` at all has not
 * said anything, so each feature is assumed available: the four Sidekick apps already call tools
 * on such hosts, and a refused ui/message is a silent no-op. A host that sends the object is
 * believed: a key that is missing means the feature is missing.
 */
export function featuresFrom(capabilities: unknown): HostFeatures {
  if (
    typeof capabilities !== "object" ||
    capabilities === null ||
    Array.isArray(capabilities)
  )
    return { serverTools: true, message: true, openLinks: true };
  const declared = capabilities as Record<string, unknown>;
  const has = (key: string) =>
    typeof declared[key] === "object" && declared[key] !== null;
  return {
    serverTools: has("serverTools"),
    message: has("message"),
    openLinks: has("openLinks"),
  };
}
export type HostToolResult = { structuredContent: unknown; isError: boolean };
/**
 * A tools/call the server answered with isError. `code` is the server's closed error code
 * (for example "forbidden") when present; the message stays generic so no backend text leaks.
 */
export class HostToolError extends Error {
  readonly code: string | undefined;
  constructor(code: string | undefined) {
    super("Tool request failed");
    this.name = "HostToolError";
    this.code = code;
  }
}

/** Hard cap on the text sent to the host model; longer summaries are cut, not rejected. */
export const MODEL_CONTEXT_MAX_CHARS = 500;
/** An identical summary sent again within this window is skipped. */
export const MODEL_CONTEXT_DEBOUNCE_MS = 2_000;

export type HostBridge = {
  /** ui/initialize handshake; resolves the host context once the app is initialized. */
  initialize: () => Promise<HostContext>;
  /** tools/call through the host. Resolves structuredContent or rejects with HostToolError. */
  call: <T>(name: string, args: object) => Promise<T>;
  /**
   * ui/request-display-mode. Resolves the mode the host actually set, which may differ from
   * the requested one; the caller must handle that. Rejects on a host error or unknown mode.
   */
  requestDisplayMode: (mode: DisplayMode) => Promise<DisplayMode>;
  /**
   * ui/update-model-context: tells the host model what the user just did, for future turns.
   * Pass only a short description of the action, for example "Flyttade uppgift <id> till Klar".
   * Callers must never send journal text (diary entries), per docs/decisions/log.md D-058 (logs and telemetry never carry user content).
   * The text is capped at 500 characters, and an identical summary sent again within 2 seconds
   * is skipped. The 2026-01-26 spec defines no per-method capability flag, so support follows
   * from the negotiated protocol version. Before the handshake, after teardown, or when the
   * host refuses, this is a silent no-op that never throws.
   */
  updateModelContext: (summary: string) => Promise<void>;
  /**
   * ui/message: puts a short user message in the conversation, so Claude answers it (for example
   * "Öppna Dagbok"). Resolves true when the host accepted it. Before the handshake, after teardown,
   * when the host declared hostCapabilities without `message`, or when the host refuses or fails,
   * nothing is shown and this resolves false; it never throws. The text is capped at 500
   * characters, and an identical text sent again within 2 seconds is skipped (resolves false).
   */
  sendMessage: (text: string) => Promise<boolean>;
  /**
   * ui/open-link (SEP-1865, draft; params `{ url }`): asks the host to open a link. Only mailto:, tel: and https: are
   * passed on; any other scheme resolves false and nothing is sent. With the `openLinks` capability the host opens
   * it, and a host refusal resolves false without a fallback, since the host decides. Without the capability the link
   * opens in a new tab through <a target="_blank">. Resolves true when sent or opened. Before the handshake and after
   * teardown it resolves false. It never throws.
   */
  openLink: (url: string) => Promise<boolean>;
  /** What the host supports. All true before the handshake and for hosts that declare nothing. */
  getFeatures: () => HostFeatures;
  onToolResult: (listener: (result: HostToolResult) => void) => void;
  /** ui/notifications/tool-input: the arguments of the tool call, before its result arrives. */
  onToolInput: (listener: (args: Record<string, unknown>) => void) => void;
  /** ui/notifications/tool-cancelled: the host stopped the tool call; `reason` only when a string. */
  onToolCancelled: (listener: (info: { reason?: string }) => void) => void;
  /** Receives the merged host context after every host-context-changed. */
  onHostContext: (listener: (context: HostContext) => void) => void;
  /** Runs before the bridge closes; the app unmounts its view here. */
  onTeardown: (listener: () => void) => void;
};

/** True for a link the bridge may pass on: mailto:, tel: or https:. Anything else, javascript: included, is refused. */
export function isAllowedLinkUrl(url: string): boolean {
  return /^(?:mailto|tel|https):/i.test(url.trim());
}

/** The fallback when the host cannot open links: a new tab, through a plain anchor. */
function openInNewTab(url: string) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.click();
}

function hasId(id: unknown): boolean {
  return id !== undefined && id !== null;
}

/** Sidekick error results carry a short closed code; anything else is dropped. */
function errorCode(structured: unknown): string | undefined {
  const code = (structured as { code?: unknown } | null | undefined)?.code;
  return typeof code === "string" && code.length <= 64 ? code : undefined;
}

export function createHostBridge(app: {
  name: string;
  version: string;
}): HostBridge {
  let sequence = 0;
  let closed = false;
  let handshakeDone = false;
  let lastContext: { text: string; sentAt: number } | undefined;
  let lastMessage: { text: string; sentAt: number } | undefined;
  let features: HostFeatures = featuresFrom(undefined);
  const pending = new Map<
    number,
    {
      resolve: (value: unknown) => void;
      reject: () => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();
  const toolResultListeners: ((result: HostToolResult) => void)[] = [];
  const toolInputListeners: ((args: Record<string, unknown>) => void)[] = [];
  const toolCancelledListeners: ((info: { reason?: string }) => void)[] = [];
  const hostContextListeners: ((context: HostContext) => void)[] = [];
  const teardownListeners: (() => void)[] = [];
  /** The ui/initialize context with every later host-context-changed merged in. */
  let hostContext: HostContext = {};

  function send(message: object) {
    window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");
  }
  function request(method: string, params: object): Promise<unknown> {
    if (closed) return Promise.reject(new Error("Closed"));
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const fail = () => reject(new Error("Host request failed"));
      const timer = setTimeout(() => {
        pending.delete(id);
        fail();
      }, 30_000);
      pending.set(id, { resolve, reject: fail, timer });
      send({ id, method, params });
    });
  }
  let ready: Promise<void>;
  let readyResolve: () => void = () => {};
  let readyReject: () => void = () => {};
  let readyFailed = false;
  /** The promise every command waits for. Armed again by a retried handshake after a failed one. */
  function armReady() {
    readyFailed = false;
    ready = new Promise<void>((resolve, reject) => {
      readyResolve = resolve;
      readyReject = () => {
        readyFailed = true;
        reject(new Error("Host unavailable"));
      };
    });
    // A failed handshake is reported by the app; consume rejection before the first command.
    void ready.catch(() => {});
  }
  armReady();
  let lastSize = { width: 0, height: 0 };
  const observer = new ResizeObserver(() => {
    const rect = document.body.getBoundingClientRect();
    const width = Math.ceil(rect.width);
    const height = Math.ceil(rect.height);
    if (width !== lastSize.width || height !== lastSize.height) {
      lastSize = { width, height };
      send({
        method: "ui/notifications/size-changed",
        params: { width, height },
      });
    }
  });

  const onMessage = (event: MessageEvent) => {
    if (
      event.source !== window.parent ||
      closed ||
      !event.data ||
      typeof event.data !== "object"
    )
      return;
    const message = event.data as {
      jsonrpc?: string;
      id?: unknown;
      result?: unknown;
      error?: unknown;
      method?: string;
      params?: Record<string, unknown>;
    };
    if (message.jsonrpc !== "2.0") return;
    // Only numeric ids are ours to correlate; anything else is not a reply to a pending request.
    if (typeof message.id === "number" && !message.method) {
      const waiter = pending.get(message.id);
      if (waiter) {
        clearTimeout(waiter.timer);
        pending.delete(message.id);
        if (message.error) waiter.reject();
        else waiter.resolve(message.result);
      }
    } else if (message.method === "ui/notifications/tool-result") {
      const result: HostToolResult = {
        structuredContent: message.params?.structuredContent,
        isError: Boolean(message.params?.isError),
      };
      for (const listener of toolResultListeners) listener(result);
    } else if (message.method === "ui/notifications/tool-input") {
      const args = message.params?.arguments;
      const input =
        typeof args === "object" && args !== null && !Array.isArray(args)
          ? (args as Record<string, unknown>)
          : {};
      for (const listener of toolInputListeners) listener(input);
    } else if (message.method === "ui/notifications/tool-cancelled") {
      const reason = message.params?.reason;
      const info = typeof reason === "string" ? { reason } : {};
      for (const listener of toolCancelledListeners) listener(info);
    } else if (message.method === "ui/notifications/host-context-changed") {
      // Partial updates are merged at the top level; a changed field replaces the old value.
      hostContext = {
        ...hostContext,
        ...((message.params ?? {}) as HostContext),
      };
      applyHostStyle(hostContext, document.documentElement);
      for (const listener of hostContextListeners) listener(hostContext);
    } else if (message.method === "ping") {
      // A ping without an id is a notification and gets no reply.
      if (hasId(message.id)) send({ id: message.id, result: {} });
    } else if (message.method === "ui/resource-teardown") {
      closed = true;
      observer.disconnect();
      window.removeEventListener("message", onMessage);
      for (const listener of teardownListeners) listener();
      for (const waiter of pending.values()) {
        clearTimeout(waiter.timer);
        waiter.reject();
      }
      pending.clear();
      if (hasId(message.id)) send({ id: message.id, result: {} });
    }
  };
  window.addEventListener("message", onMessage);

  return {
    initialize() {
      // A retry after a failed handshake: commands wait for this attempt, not for the one that failed.
      if (readyFailed) armReady();
      return request("ui/initialize", {
        protocolVersion: MCP_APPS_PROTOCOL_VERSION,
        appInfo: app,
        appCapabilities: { availableDisplayModes: APP_DISPLAY_MODES },
      })
        .then((value) => {
          const host = value as {
            protocolVersion?: string;
            hostContext?: HostContext;
            hostCapabilities?: unknown;
          };
          if (!isSupportedProtocolVersion(host.protocolVersion))
            throw new Error("Unsupported protocol");
          const context = host.hostContext ?? {};
          hostContext = { ...context };
          features = featuresFrom(host.hostCapabilities);
          applyHostStyle(hostContext, document.documentElement);
          send({ method: "ui/notifications/initialized", params: {} });
          handshakeDone = true;
          readyResolve();
          observer.observe(document.body);
          return context;
        })
        .catch((error: unknown) => {
          readyReject();
          throw error;
        });
    },
    async call<T>(name: string, args: object): Promise<T> {
      await ready;
      const raw = await request("tools/call", { name, arguments: args });
      const result = raw as { isError?: boolean; structuredContent?: T };
      if (result.isError)
        throw new HostToolError(errorCode(result.structuredContent));
      if (result.structuredContent === undefined)
        throw new HostToolError(undefined);
      return result.structuredContent;
    },
    async requestDisplayMode(mode) {
      await ready;
      const raw = (await request("ui/request-display-mode", { mode })) as
        | { mode?: unknown }
        | undefined;
      const actual = raw?.mode;
      if (typeof actual !== "string" || !DISPLAY_MODES.includes(actual))
        throw new Error("Unsupported display mode");
      return actual as DisplayMode;
    },
    updateModelContext(summary) {
      if (closed || !handshakeDone) return Promise.resolve();
      const text = Array.from(summary.trim())
        .slice(0, MODEL_CONTEXT_MAX_CHARS)
        .join("");
      if (text === "") return Promise.resolve();
      const now = Date.now();
      if (
        lastContext?.text === text &&
        now - lastContext.sentAt < MODEL_CONTEXT_DEBOUNCE_MS
      )
        return Promise.resolve();
      lastContext = { text, sentAt: now };
      // A host that refuses or fails must not break the app, so both outcomes are swallowed.
      return request("ui/update-model-context", {
        content: [{ type: "text", text }],
      }).then(
        () => undefined,
        () => undefined,
      );
    },
    sendMessage(text) {
      if (closed || !handshakeDone || !features.message)
        return Promise.resolve(false);
      const clipped = Array.from(text.trim())
        .slice(0, MODEL_CONTEXT_MAX_CHARS)
        .join("");
      if (clipped === "") return Promise.resolve(false);
      const now = Date.now();
      if (
        lastMessage?.text === clipped &&
        now - lastMessage.sentAt < MODEL_CONTEXT_DEBOUNCE_MS
      )
        return Promise.resolve(false);
      lastMessage = { text: clipped, sentAt: now };
      // A host that refuses (consent denied) or fails must not break the app.
      return request("ui/message", {
        role: "user",
        content: { type: "text", text: clipped },
      }).then(
        () => true,
        () => false,
      );
    },
    openLink(url) {
      const clean = url.trim();
      if (closed || !handshakeDone || !isAllowedLinkUrl(clean))
        return Promise.resolve(false);
      if (!features.openLinks) {
        openInNewTab(clean);
        return Promise.resolve(true);
      }
      return request("ui/open-link", { url: clean }).then(
        () => true,
        () => false,
      );
    },
    getFeatures() {
      return features;
    },
    onToolResult(listener) {
      toolResultListeners.push(listener);
    },
    onToolInput(listener) {
      toolInputListeners.push(listener);
    },
    onToolCancelled(listener) {
      toolCancelledListeners.push(listener);
    },
    onHostContext(listener) {
      hostContextListeners.push(listener);
    },
    onTeardown(listener) {
      teardownListeners.push(listener);
    },
  };
}
