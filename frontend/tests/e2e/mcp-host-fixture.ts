// Playwright runs this file outside Vitest: it reads the bundled app HTML (and font files) from disk to serve them to the simulated host.
import { readFileSync } from "node:fs";
import type { FrameLocator, Locator, Page } from "@playwright/test";

// Shared SIMULATED HOST for the MCP App e2e specs. It is not a real Claude or Sidekick host: it
// answers the app's postMessage protocol (ui/initialize, tools/call, ui/request-display-mode) from
// fixtures and sends the host notifications the tests choose (tool-input, tool-result,
// host-context-changed). No backend, no database, no network: every tool answer is a fixture.
// The sandboxed iframe is the same pattern as ui-language-mcp-app.spec.ts and work-mcp-app.spec.ts.

export type SimulatedCall = {
  name: string;
  arguments: Record<string, unknown>;
};
export type SimulatedHostState = {
  initialized: boolean;
  calls: SimulatedCall[];
  displayModeRequests: string[];
};
export type SimulatedHostConfig = {
  /** Host context returned by ui/initialize. Partial updates come later via setHostContext. */
  hostContext: Record<string, unknown>;
  /**
   * hostCapabilities of the ui/initialize answer. The default is an empty object (a host that proxies
   * nothing), so the room strip stays away; navigation specs pass { serverTools: {}, message: {} }.
   */
  hostCapabilities?: Record<string, unknown>;
  /**
   * Answers per tool name, as the full tools/call result. A tool without an answer gets isError.
   * { __sequence: [a, b] } answers a first, then b for every later call.
   * { __byArgument: { key, answers } } answers by the value of one argument.
   */
  replies: Record<string, unknown>;
};
export type OpenedApp = {
  app: FrameLocator;
  failures: string[];
  networkRequests: () => number;
};

/**
 * The Sidekick app locale, SIDEKICK_MCP_APP_LOCALE. The host's locale never changes the apps.
 */
export type AppLocale = "sv" | "en";

/**
 * Declares the Sidekick app locale in the document head, as the backend does for every app
 * resource. Without the declaration the app is Swedish, whatever the simulated host reports.
 */
export function withAppLocale(html: string, locale: AppLocale = "sv"): string {
  return html.replace(
    "<head>",
    `<head><meta name="sidekick-app-locale" content="${locale}">`,
  );
}

const builtAppCache = new Map<string, string>();

/**
 * The Work and Journal Apps are built into the backend; the specs read the built HTML. The read and
 * the locale patch are done once per (file, locale) and reused, because the built HTML is ~268 kB.
 */
export function readBuiltApp(
  _file: "work" | "journal" | "shopping" | "control" | "sidekick",
  locale: AppLocale = "sv",
): string {
  // All four resources serve the same unified app, whichever room a spec exercises.
  const file = "sidekick";
  const key = `${file}:${locale}`;
  const cached = builtAppCache.get(key);
  if (cached !== undefined) return cached;
  const html = withAppLocale(
    readFileSync(`../backend/src/sidekick/mcp/apps/${file}.html`, "utf8"),
    locale,
  );
  builtAppCache.set(key, html);
  return html;
}

/**
 * Installs the simulated host in the page. Written as one self-contained function, because
 * Playwright serialises its source into the browser. It exposes window.simulatedHost, which the
 * helpers below use to send host messages to the iframe.
 */
function installSimulatedHost({
  resource,
  config,
}: {
  resource: string;
  config: SimulatedHostConfig;
}) {
  const frame = document.querySelector("iframe")!;
  const state: SimulatedHostState = {
    initialized: false,
    calls: [],
    displayModeRequests: [],
  };
  const sequenceCounts = new Map<string, number>();
  const send = (body: object) =>
    frame.contentWindow!.postMessage({ jsonrpc: "2.0", ...body }, "*");
  // Changes the answer to one tool for the rest of the test (a server that remembers a write).
  const setReply = (name: string, reply: unknown) => {
    config.replies[name] = reply;
    sequenceCounts.delete(name);
  };
  Object.assign(window, { simulatedHost: { state, send, setReply } });
  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow) return;
    const message = event.data as {
      id?: number;
      method: string;
      params: {
        name?: string;
        arguments?: Record<string, unknown>;
        mode?: string;
      };
    };
    if (message.method === "ui/initialize")
      send({
        id: message.id,
        result: {
          protocolVersion: "2026-01-26",
          hostCapabilities: config.hostCapabilities ?? {},
          hostInfo: { name: "Simulated host", version: "1" },
          hostContext: config.hostContext,
        },
      });
    else if (message.method === "ui/notifications/initialized")
      state.initialized = true;
    else if (message.method === "ui/request-display-mode") {
      state.displayModeRequests.push(String(message.params.mode));
      send({ id: message.id, result: { mode: message.params.mode } });
    } else if (message.method === "tools/call") {
      const name = message.params.name ?? "";
      state.calls.push({ name, arguments: message.params.arguments ?? {} });
      // { __sequence: [a, b] } answers a, then b, and keeps answering b: a read that changes after a write.
      const reply = config.replies[name] as
        | {
            __sequence?: unknown[];
            __byArgument?: { key: string; answers: Record<string, unknown> };
          }
        | undefined;
      let answer: unknown = reply;
      // { __byArgument: { key, answers } } answers by the value of one argument (a record id).
      if (reply?.__byArgument) {
        const { key, answers } = reply.__byArgument;
        answer = answers[String(message.params.arguments?.[key])];
      }
      if (Array.isArray(reply?.__sequence)) {
        const seen = sequenceCounts.get(name) ?? 0;
        sequenceCounts.set(name, seen + 1);
        answer = reply.__sequence[Math.min(seen, reply.__sequence.length - 1)];
      }
      send({ id: message.id, result: answer ?? { isError: true } });
    }
  });
  frame.srcdoc = resource;
}

/**
 * Opens one app in a sized iframe on the simulated host. All network requests are aborted and
 * page errors are collected. The app is not sent any tool input or result; the test delivers them.
 */
export async function openSimulatedApp(
  page: Page,
  options: {
    resource: string;
    width: number;
    height: number;
  } & SimulatedHostConfig,
): Promise<OpenedApp> {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  let networkRequests = 0;
  await page.route("**/*", async (route) => {
    networkRequests++;
    await route.abort();
  });
  await page.setViewportSize({ width: options.width, height: options.height });
  // The outer page has no body margin, so the iframe alone decides its width.
  await page.setContent(
    `<style>html,body{margin:0}</style><iframe title="Sidekick" sandbox="allow-scripts" style="display:block;width:${options.width}px;height:${options.height}px;border:0"></iframe>`,
  );
  await page.evaluate(installSimulatedHost, {
    resource: options.resource,
    config: {
      hostContext: options.hostContext,
      replies: options.replies,
      hostCapabilities: options.hostCapabilities,
    },
  });
  return {
    app: page.frameLocator("iframe"),
    failures,
    networkRequests: () => networkRequests,
  };
}

/** Waits until the app has completed ui/initialize and sent ui/notifications/initialized. */
export async function waitForAppInitialized(page: Page) {
  await page.waitForFunction(
    () =>
      (window as unknown as { simulatedHost: { state: SimulatedHostState } })
        .simulatedHost.state.initialized,
  );
}

/** Longest wait in settled(). A stuck app then fails its own assertions instead of hanging the test. */
const SETTLE_CAP_MS = 5000;

/**
 * Waits until the app in the frame has finished drawing, instead of sleeping for a fixed time. It
 * waits for: one yield so render work queued by the last message can run, no aria-busy or skeleton
 * left, fonts loaded, all finite running CSS animations finished (infinite ones such as the skeleton
 * pulse are skipped), and two painted frames. Gives up after SETTLE_CAP_MS. Written as one
 * self-contained function, because Playwright serialises its source into the iframe.
 */
export async function settled(frame: FrameLocator): Promise<void> {
  await frame
    .locator("html")
    .evaluate(async (_root: Element, capMs: number) => {
      const nextFrame = () =>
        new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const busy = () =>
        document.querySelector('[aria-busy="true"], .sk-skeleton') !== null;
      const finiteRunning = () =>
        document.getAnimations().filter((animation) => {
          const iterations = (
            animation.effect as KeyframeEffect | null
          )?.getTiming().iterations;
          return iterations !== Infinity && animation.playState === "running";
        });
      const drawn = async () => {
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
        while (busy()) await nextFrame();
        await document.fonts.ready;
        await Promise.all(
          finiteRunning().map((animation) =>
            animation.finished.catch(() => undefined),
          ),
        );
        await nextFrame();
        await nextFrame();
      };
      let timer: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([
        drawn(),
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, capMs);
        }),
      ]);
      clearTimeout(timer);
    }, SETTLE_CAP_MS);
}

/** Reads the simulated host state: handshake, tools/call requests and display-mode requests. */
export async function simulatedHostState(
  page: Page,
): Promise<SimulatedHostState> {
  return page.evaluate(
    () =>
      (window as unknown as { simulatedHost: { state: SimulatedHostState } })
        .simulatedHost.state,
  );
}

/** Sends ui/notifications/tool-input: the arguments of the tool call, before its result. */
export async function deliverToolInput(
  page: Page,
  args: Record<string, unknown>,
) {
  await page.evaluate(
    (params) =>
      (
        window as unknown as {
          simulatedHost: { send: (body: object) => void };
        }
      ).simulatedHost.send({
        method: "ui/notifications/tool-input",
        params,
      }),
    { arguments: args },
  );
}

/**
 * Sends ui/notifications/tool-result with the given structuredContent. Resolves with the browser
 * clock (performance.timeOrigin + performance.now(), epoch milliseconds) read just before the
 * message is posted, for specs that time the app from inside the browser.
 */
export async function deliverToolResult(
  page: Page,
  structuredContent: unknown,
  isError = false,
): Promise<number> {
  return page.evaluate(
    (params) => {
      const sentAt = performance.timeOrigin + performance.now();
      (
        window as unknown as {
          simulatedHost: { send: (body: object) => void };
        }
      ).simulatedHost.send({
        method: "ui/notifications/tool-result",
        params,
      });
      return sentAt;
    },
    { structuredContent, isError },
  );
}

/** Changes what the simulated host answers to one tool from now on (a server that remembers a write). */
export async function setHostReply(page: Page, name: string, reply: unknown) {
  await page.evaluate(
    ([toolName, answer]) =>
      (
        window as unknown as {
          simulatedHost: { setReply: (name: string, reply: unknown) => void };
        }
      ).simulatedHost.setReply(toolName, answer),
    [name, reply] as const,
  );
}

/** Sends ui/notifications/host-context-changed; the app merges the fields it receives. */
export async function setHostContext(
  page: Page,
  changes: Record<string, unknown>,
) {
  await page.evaluate(
    (params) =>
      (
        window as unknown as {
          simulatedHost: { send: (body: object) => void };
        }
      ).simulatedHost.send({
        method: "ui/notifications/host-context-changed",
        params,
      }),
    changes,
  );
}

/**
 * The touch target a finger actually gets: the element's box, extended by its `::after` when that
 * pseudo-element is absolutely positioned and reaches outside the box (negative top/bottom/left/right).
 * The compact inline-card buttons are 40 px visible with a 48 px hit area made this way (design rule:
 * compact 40 visible / 48 hit). The `::after` is placed from the padding box, inside the element's border, so
 * its reach is added to the padding box, not to the border box (a 1 px edge and an inset of −4 make 46, not 48).
 * A button without such an `::after` is measured by its box alone, so a genuinely small target is still caught.
 */
export async function effectiveTargetSize(
  locator: Locator,
): Promise<{ width: number; height: number } | null> {
  const box = await locator.boundingBox();
  if (!box) return null;
  const reach = await locator.evaluate((element) => {
    const style = getComputedStyle(element, "::after");
    if (style.content === "none" || style.position !== "absolute")
      return { x: 0, y: 0 };
    const own = getComputedStyle(element);
    const px = (value: string) => Number.parseFloat(value) || 0;
    // How far the ::after reaches past the border box on one side: its offset from the padding box, less the border
    // it starts inside of. The target is the border box and the ::after together.
    const past = (offset: string, border: string) =>
      Math.max(0, -px(offset) - px(border));
    return {
      x:
        past(style.left, own.borderLeftWidth) +
        past(style.right, own.borderRightWidth),
      y:
        past(style.top, own.borderTopWidth) +
        past(style.bottom, own.borderBottomWidth),
    };
  });
  return { width: box.width + reach.x, height: box.height + reach.y };
}
