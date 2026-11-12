/**
 * The one entry of the Sidekick MCP App (MCP Apps 2026-01-26 host bridge). It serves all four app
 * resources (work, journal, shopping, control): the router names the room and view from the tool
 * that opened the card, and the shell draws that room, inline as a card or full with the room strip.
 * No network, credential or backend URL in the view.
 */
import "./ui/tokens.css";
import "./ui/family.css";
import { createRoot } from "react-dom/client";
import { APP_VERSION } from "./app-version";
import { createHostBridge, type HostContext } from "./bridge";
import { AwaitingResult } from "./awaiting";
import { appLocale, applyAppLocale } from "./app-locale";
import { SidekickShell } from "./sidekick-shell";
import { roomEnabled } from "./enabled-rooms";
import { LicenseHostContext, type LicenseHost } from "./license-mark";
import {
  SIDEKICK_ROOMS,
  RoomHostContext,
  idInData,
  type RoomHost,
} from "./sidekick-rooms";
import { ROOT_VIEW, type NavEntry } from "./nav-state";
import { fullscreenOffered, roomModeOf } from "./room-types";
import { routeFor, type Route } from "./router";
import { StartupError } from "./ui/error-boundary";

const bridge = createHostBridge({ name: "Sidekick", version: APP_VERSION });
const root = createRoot(document.getElementById("root")!);
const locale = appLocale();
applyAppLocale(locale);

// Until the first tool result, every kind of result included, the app shows AwaitingResult.
let start: NavEntry | undefined;
// Counts the results that re-rooted the app; the shell is keyed by it, so it starts over.
let resultCount = 0;
// True once a room expanded inline, or the host granted fullscreen before its own context said so.
let expanded = false;
// True when the expansion was a fullscreen request the host granted, so an explicit inline report ends it.
let grantedFullscreen = false;
// A record the room that asked for the full view wants shown at once (an entry of the day glance).
let openAt: NavEntry | undefined;
let hostContext: HostContext = {};

/** The route of a result, unless its room is off on this instance (SIDEKICK_ENABLED_ROOMS): that room is not drawn. */
function routeInEnabledRoom(route: Route | undefined): Route | undefined {
  return route && roomEnabled(route.room) ? route : undefined;
}

/** Stable for the life of the page; the rooms read the host context at render time. */
const host: RoomHost = {
  transport: bridge,
  fullscreenAvailable: () =>
    fullscreenOffered(
      hostContext.availableDisplayModes,
      hostContext.displayMode,
    ),
  onExpand: (target) => {
    if (expanded && !target) return;
    expanded = true;
    grantedFullscreen = fullscreenOffered(
      hostContext.availableDisplayModes,
      hostContext.displayMode,
    );
    if (target) openAt = target;
    render();
  },
};

/** The user folds the expanded view in again. A host that did grant fullscreen is asked to leave it. */
function collapse() {
  const leaveHostFullscreen = grantedFullscreen;
  expanded = false;
  grantedFullscreen = false;
  openAt = undefined;
  render();
  if (leaveHostFullscreen)
    void bridge.requestDisplayMode("inline").catch(() => {});
}

/**
 * The first Intl object of a page costs tens of milliseconds (ICU set-up). `initialized` has gone to the
 * host, which now has a round trip to answer with the tool result; building one date and one number
 * format then keeps that cost off the first card's render. It runs after the handshake, never before, so
 * it cannot delay it.
 */
function warmIntl() {
  setTimeout(() => {
    try {
      const tag = locale === "en" ? "en-GB" : "sv-SE";
      new Intl.DateTimeFormat(tag, {
        weekday: "long",
        day: "numeric",
        month: "short",
        timeZone: "UTC",
      }).format(0);
      new Intl.NumberFormat(tag, { maximumFractionDigits: 1 }).format(1.5);
    } catch {
      // Only a head start; the rooms build their own formats when they need them.
    }
  }, 0);
}

// True once the host has answered ui/initialize: only then do its display mode and tool name count.
let handshakeDone = false;

function render() {
  if (!start) {
    // The host context of the handshake may name the tool that opened the card (toolInfo, optional in MCP
    // Apps 2026-01-26). Then the placeholder marks that room and draws its header; before it, no room is known.
    const waiting = handshakeDone
      ? routeInEnabledRoom(
          routeFor({
            toolName: hostContext.toolInfo?.tool?.name,
            isError: true,
          }),
        )
      : undefined;
    root.render(
      <AwaitingResult
        locale={locale}
        room={waiting?.room}
        view={waiting?.view}
        full={
          !handshakeDone ||
          hostContext.displayMode === undefined ||
          roomModeOf(hostContext.displayMode) === "full"
        }
      />,
    );
    return;
  }
  const full = expanded || roomModeOf(hostContext.displayMode) === "full";
  root.render(
    <LicenseHostContext.Provider value={licenseHost()}>
      <RoomHostContext.Provider value={host}>
        <SidekickShell
          locale={locale}
          rooms={SIDEKICK_ROOMS}
          start={start}
          openAt={openAt}
          full={full}
          onCollapse={
            // Only an expansion the host does not show as fullscreen can be folded in again from here.
            expanded && roomModeOf(hostContext.displayMode) !== "full"
              ? collapse
              : undefined
          }
          features={bridge.getFeatures()}
          onModelContext={(line) => void bridge.updateModelContext(line)}
          onSendMessage={(text) => bridge.sendMessage(text)}
        />
      </RoomHostContext.Provider>
    </LicenseHostContext.Provider>,
  );
}

/**
 * The license row's host: set_license_key (app-only, the model never sees it) and "Köp licens" through the bridge.
 * A host that cannot proxy tool calls gets no key field.
 */
const licenseCall: LicenseHost["call"] = (name, args) =>
  bridge.call(name, args);
const licenseOpenLink: LicenseHost["openLink"] = (url) => bridge.openLink(url);
const licenseHosts: Record<"tools" | "none", LicenseHost> = {
  tools: { call: licenseCall, openLink: licenseOpenLink },
  none: { openLink: licenseOpenLink },
};
function licenseHost(): LicenseHost {
  return licenseHosts[bridge.getFeatures().serverTools ? "tools" : "none"];
}

// Every tool result reaches the router, errors included. A result the router does not know keeps what
// is shown; with nothing shown yet, Work answers (an error there reads as the shared notice).
bridge.onToolResult(({ structuredContent, isError }) => {
  const routed = routeFor({
    toolName: hostContext.toolInfo?.tool?.name,
    structuredContent,
    isError,
  });
  const route = routeInEnabledRoom(routed);
  // A result of a room that is off (an old conversation's card) is not drawn: it is ignored, or Work opens empty.
  const ofOffRoom = routed !== undefined && route === undefined;
  if (ofOffRoom && start) return;
  // An error with no tool name has no shape to route by; it lands in the room the card is in.
  if (!route && start && !isError) return;
  const room = route?.room ?? start?.room ?? "work";
  const opened: NavEntry = {
    room,
    // An error with no route keeps the view the card is on, so the room can keep it.
    view: route?.view ?? (start?.room === room ? start.view : ROOT_VIEW),
    data: ofOffRoom ? undefined : structuredContent,
    isError: ofOffRoom ? undefined : isError,
    resultId: resultCount + 1,
  };
  // A card on one record knows it by id, so a cross-link back to the same record is a loop, not a new step.
  start = { ...opened, id: idInData(opened) };
  resultCount++;
  expanded = false;
  grantedFullscreen = false;
  openAt = undefined;
  render();
});
bridge.onHostContext((context) => {
  const before = hostContext.displayMode;
  hostContext = { ...hostContext, ...context };
  // A display mode change that the host reports is the truth again; the local expansion only bridges the gap.
  if (hostContext.displayMode !== before) {
    expanded = false;
    grantedFullscreen = false;
    openAt = undefined;
  } else if (
    expanded &&
    grantedFullscreen &&
    context.displayMode !== undefined &&
    context.displayMode !== "fullscreen"
  ) {
    // The host granted fullscreen without ever reporting it, and now reports inline: the card is back.
    expanded = false;
    grantedFullscreen = false;
    openAt = undefined;
  }
  render();
});
bridge.onTeardown(() => root.unmount());
// The skeleton is drawn now, not after the host's answer to ui/initialize: the handshake costs a round trip.
render();
// The handshake starts from a microtask, not from inside the start-up script: a message posted while the
// bundle's own frames are on the stack makes an attached inspector (DevTools, a test driver) read the
// source positions of the whole bundle first, which cost ~0.4 s at 4x CPU. Nothing else changes.
function startHandshake() {
  bridge
    .initialize()
    .then((initialContext) => {
      hostContext = initialContext;
      handshakeDone = true;
      render();
      warmIntl();
    })
    .catch(() => {
      // No detail of the failure is shown; "Försök igen" draws the skeleton and runs the handshake again.
      root.render(
        <StartupError
          locale={locale}
          onRetry={() => {
            render();
            startHandshake();
          }}
        />,
      );
    });
}
queueMicrotask(startHandshake);
