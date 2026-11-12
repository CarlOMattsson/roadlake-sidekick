import { App } from "@capacitor/app";

import { parsePairingLink } from "./pairing-link";
import type { MobilePlatform } from "./platform";

/** The deep link a widget tap or a notification opens the app with: sidekick://open?view=task&id=... */
const LAUNCH_URL_PREFIX = "sidekick://open?";

/** The query part of a launch URL ("?view=task&id=..."), or "" for any other URL. The hint itself is validated later. */
export function launchSearchOf(url: string | undefined): string {
  if (typeof url !== "string" || !url.startsWith(LAUNCH_URL_PREFIX)) return "";
  const search = url.slice(LAUNCH_URL_PREFIX.length - 1);
  const fragment = search.indexOf("#");
  return fragment === -1 ? search : search.slice(0, fragment);
}

/**
 * The Android platform of the mobile app, on Capacitor's App plugin.
 *
 * - Back: one permanent `backButton` listener (Capacitor falls back to WebView history when there is none, which is
 *   wrong here). It offers Back to the registered handler, the innermost screen first; when no handler takes it, the
 *   app is at its root and leaves (`exitApp`), as Android expects of the launcher activity.
 * - Resume: `appStateChange` with isActive, when the app comes back to the foreground.
 * - Launch: the intent's data URL when the app was started by a hint (`getLaunchUrl`), and `appUrlOpen` while it runs.
 *   A pairing link (`sidekick://pair?…`) comes the same way and fills in the pairing form (pairing-gate.tsx).
 * - Insets: Capacitor's SystemBars publishes them as CSS variables, so the page reads them from the CSS (insets.ts).
 */
export async function createNativePlatform(): Promise<MobilePlatform> {
  const launch = await App.getLaunchUrl();
  const initialSearch = launchSearchOf(launch?.url);
  const initialPairingLink = parsePairingLink(launch?.url);

  // Innermost last. A handler returns true when it went back one layer.
  const backHandlers: Array<() => boolean> = [];
  await App.addListener("backButton", () => {
    const handler = backHandlers.at(-1);
    if (!handler?.()) void App.exitApp();
  });

  return {
    onBack(handler) {
      backHandlers.push(handler);
      return () => {
        const index = backHandlers.lastIndexOf(handler);
        if (index !== -1) backHandlers.splice(index, 1);
      };
    },
    launchSearch: () => initialSearch,
    onLaunchSearch(listener) {
      const handle = App.addListener("appUrlOpen", (event) => {
        // A pairing link is the gate's (onPairingLink), not a hint to go to Today.
        if (!parsePairingLink(event.url)) listener(launchSearchOf(event.url));
      });
      return () => {
        void handle.then((registered) => registered.remove());
      };
    },
    pairingLink: () => initialPairingLink,
    onPairingLink(listener) {
      const handle = App.addListener("appUrlOpen", (event) => {
        const link = parsePairingLink(event.url);
        if (link) listener(link);
      });
      return () => {
        void handle.then((registered) => registered.remove());
      };
    },
    onResume(listener) {
      const handle = App.addListener("appStateChange", (state) => {
        if (state.isActive) listener();
      });
      return () => {
        void handle.then((registered) => registered.remove());
      };
    },
    safeAreaInsets: () => undefined,
  };
}
