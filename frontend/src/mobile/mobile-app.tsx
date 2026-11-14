/**
 * The mobile shell: the Work room (Idag, Agenda, a Task with its Steps, Projekt), the Journal and Shopping, in full
 * mode, over CompanionRoomTransport. It is the Sidekick shell and the rooms as they are; this file adds only what a
 * phone around them needs: the room host for a transport that is not a postMessage bridge, system Back, the launch
 * hint, and the safe-area insets. No room is copied and there is no model to message. The room strip stands at the
 * top with the three rooms the app serves (MOBILE_STRIP_ROOMS) that the server shows (SIDEKICK_ENABLED_ROOMS, read by
 * server-rooms.ts; with Work alone there is no strip), and the narrow room picker takes its place when they do not
 * fit; there is no bottom bar. What the app cannot answer (the AI drafts of the Journal, the
 * recipient search of Shopping) the rooms leave out themselves, by asking the transport which tools it has.
 *
 * The phone's settings (settings-panel.tsx) open from the settings entry at the end of every room's ⋯ menu, where
 * Control stands in Claude. They cover the shell, which stays mounted, and Back (‹ Arbete or system Back) returns.
 */
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type { RoomId } from "@/features/mcp-apps/router";
import { Button } from "@/features/mcp-apps/ui/button";
import { SidekickShell } from "@/features/mcp-apps/sidekick-shell";
import {
  SIDEKICK_ROOMS,
  RoomHostContext,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import {
  LicenseHostContext,
  type LicenseHost,
} from "@/features/mcp-apps/license-mark";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import type { SidekickNativePlugin } from "./sidekick-native";
import { useSafeAreaInsets } from "./insets";
import { parseLaunchHint, startEntryOf } from "./launch-hint";
import { PairingGateContext } from "./pairing-gate";
import type { MobilePlatform } from "./platform";
import { PushNotice } from "./push-notice";
import { QueueNotice, type QueueNoticeProps } from "./queue-notice";
import { useServerLicense, type ServerLicenseNative } from "./server-license";
import { useServerRooms, type ServerRoomsNative } from "./server-rooms";
import { SettingsPanel, type SettingsNative } from "./settings-panel";
import { settingsLabelsFor } from "./settings-labels";

/** The host features of the phone: rooms may call tools (the companion routes) and navigate; nothing else exists. */
const MOBILE_FEATURES = {
  serverTools: true,
  message: false,
  openLinks: false,
} as const;

/**
 * The views the companion routes serve: Agenda (with Idag) and Projekt (the hierarchy, its Projects, Domains and
 * Processes). The Status board has no route yet. Tasks and Projects open as steps on the shell's stack, as in Claude.
 */
const MOBILE_VIEWS: NonNullable<RoomHost["availableViews"]> = {
  work: ["agenda", "hierarchy"],
};

/** The rooms the strip and the room picker offer. Contacts has no companion route yet, so it stands out of them. */
const MOBILE_STRIP_ROOMS = ["work", "journal", "shopping"] as const;

/** Coming back to the foreground reads again only when the last read is older than this. */
export const RESUME_REFRESH_AFTER_MS = 30_000;

/** The tools that read; a call to one of them is a read of the room's data. */
const READ_TOOL = /^(get|list)_/;

type QueueNoticeNative = QueueNoticeProps["native"];

export type MobileAppProps = {
  transport: RoomTransport;
  platform: MobilePlatform;
  locale: AppLocale;
  /** Chooses the app's language (Inställningar' Svenska | English). Absent: no choice there. */
  onLocale?: (locale: AppLocale) => void;
  /**
   * Tells the home-screen widget the app language, reads whether push can work (the note about a missing
   * distributor) and serves the settings. Absent: the widget keeps the system language, and there is no push note and
   * no settings entry.
   */
  native?: Pick<SidekickNativePlugin, "setLocale"> &
    SettingsNative &
    ServerRoomsNative &
    ServerLicenseNative &
    QueueNoticeNative;
};

export function MobileApp({
  transport,
  platform,
  locale,
  native,
  onLocale,
}: MobileAppProps) {
  const [start, setStart] = useState(() =>
    startEntryOf(parseLaunchHint(platform.launchSearch())),
  );

  // A hint on a warm app re-roots it, as a new tool result re-roots the card in Claude.
  useEffect(
    () =>
      platform.onLaunchSearch((search) =>
        setStart(startEntryOf(parseLaunchHint(search))),
      ),
    [platform],
  );

  useSafeAreaInsets(platform);

  // The widget draws its texts in the app's language, also after the language changes. A refusal is not the page's to show.
  useEffect(() => {
    if (!native) return;
    native
      .setLocale({ tag: locale === "en" ? "en" : "sv" })
      .catch(() => undefined);
  }, [native, locale]);

  // Back in the foreground: the rooms read again in place (the shell's stale mechanism), unless a read is younger than
  // RESUME_REFRESH_AFTER_MS (the first read of the app counts, through `noting` below). The moment is taken when the event arrives, so a second event before the read starts adds none.
  const lastRead = useRef(0);
  const [staleTick, setStaleTick] = useState(0);
  // Push is read again on every return too: the owner may have installed ntfy meanwhile.
  const [pushTick, setPushTick] = useState(0);
  // The rooms the server shows (SIDEKICK_ENABLED_ROOMS), read from the pairing and from the server on each return.
  const roomsKey = useServerRooms(native, pushTick);
  // The license display state (see docs/decisions/log.md D-083: license terms), read the same way: the coin and the row in Inställningar follow it.
  useServerLicense(native, pushTick);
  useEffect(
    () =>
      platform.onResume(() => {
        setPushTick((tick) => tick + 1);
        const now = Date.now();
        if (now - lastRead.current < RESUME_REFRESH_AFTER_MS) return;
        lastRead.current = now;
        setStaleTick((tick) => tick + 1);
      }),
    [platform],
  );
  const noting = useMemo<RoomTransport>(
    () => ({
      call: (name, args) => {
        if (READ_TOOL.test(name)) lastRead.current = Date.now();
        return transport.call(name, args);
      },
      requestDisplayMode: transport.requestDisplayMode,
      updateModelContext: transport.updateModelContext,
      supportsTool: transport.supportsTool,
      supportsCall: transport.supportsCall,
      offline: transport.offline,
    }),
    [transport],
  );

  // The settings over the shell. The focus goes back to what opened them (⋯) when they close.
  const [settingsOpen, setSettingsOpen] = useState(false);
  // The room the settings were opened from: their Back leads there and is named after it.
  const [settingsFrom, setSettingsFrom] = useState<RoomId>("work");
  const opener = useRef<HTMLElement | null>(null);
  const openSettings = useCallback((from: RoomId) => {
    opener.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setSettingsFrom(from);
    setSettingsOpen(true);
  }, []);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !settingsOpen) opener.current?.focus();
    wasOpen.current = settingsOpen;
  }, [settingsOpen]);
  const gate = useContext(PairingGateContext);
  const settingsLabel = settingsLabelsFor(locale).title;
  const hostSettings = useMemo(
    () => (native ? { label: settingsLabel, onOpen: openSettings } : undefined),
    [native, settingsLabel, openSettings],
  );

  // System Back: the settings close first, then the shell's handler when it has one layer to leave, else the platform's.
  const shellBack = useRef<(() => boolean) | undefined>(undefined);
  const registerBack = useCallback((handler: (() => boolean) | undefined) => {
    shellBack.current = handler;
  }, []);
  const settingsShown = useRef(false);
  useEffect(() => {
    settingsShown.current = settingsOpen;
  }, [settingsOpen]);
  useEffect(
    () =>
      platform.onBack(() => {
        if (settingsShown.current) {
          setSettingsOpen(false);
          return true;
        }
        return shellBack.current?.() ?? false;
      }),
    [platform],
  );

  const host = useMemo<RoomHost>(
    () => ({
      transport: noting,
      // The phone is always full: no room has a fullscreen to ask for.
      fullscreenAvailable: () => false,
      onExpand: () => undefined,
      availableViews: MOBILE_VIEWS,
      hostSettings,
    }),
    [noting, hostSettings],
  );

  // The license row's host: the key through the companion transport (PUT /companion/v1/license), and the coin opens
  // Inställningar, which hold the row. `buy` is a plain link: the system browser opens it.
  const licenseHost = useMemo<LicenseHost>(
    () => ({
      call: noting.call,
      openSettings: native ? openSettings : undefined,
    }),
    [noting, native, openSettings],
  );

  // The stored rooms are read before the first draw, so a room that is off never shows, not even for a moment.
  // The shell's own background covers the screen meanwhile (no blank frame between the pairing gate and the rooms).
  if (roomsKey === undefined)
    return <div className="mobile-shell mobile-shell--loading" aria-busy />;

  return (
    <LicenseHostContext.Provider value={licenseHost}>
      <RoomHostContext.Provider value={host}>
        <div className="mobile-shell" hidden={settingsOpen}>
          {gate?.linkNotice ? (
            <div role="status" className="mobile-link-notice" lang={locale}>
              <p className="mobile-link-notice__text">{gate.linkNotice.text}</p>
              <Button variant="quiet" onClick={gate.dismissLinkNotice}>
                {gate.linkNotice.dismiss}
              </Button>
            </div>
          ) : null}
          <SidekickShell
            // Keyed on the rooms only: a language change re-renders labels in place and keeps unsaved form text.
            key={roomsKey}
            locale={locale}
            rooms={SIDEKICK_ROOMS}
            start={start}
            full
            features={MOBILE_FEATURES}
            stripRooms={MOBILE_STRIP_ROOMS}
            registerBack={registerBack}
            staleTick={staleTick}
          />
          {native ? (
            <QueueNotice
              native={native}
              locale={locale}
              refreshKey={pushTick}
            />
          ) : null}
          {native ? (
            <PushNotice native={native} locale={locale} refreshKey={pushTick} />
          ) : null}
        </div>
        {native && settingsOpen ? (
          <SettingsPanel
            native={native}
            locale={locale}
            from={settingsFrom}
            refreshKey={pushTick}
            onLocale={onLocale}
            onBack={closeSettings}
            onUnpaired={(serverRevoked) => gate?.unpaired(serverRevoked)}
          />
        ) : null}
      </RoomHostContext.Provider>
    </LicenseHostContext.Provider>
  );
}
