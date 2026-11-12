/**
 * What the mobile entry needs from the platform around it, behind one small interface. The Android shell fills it
 * later (system Back, the launch Intent, window insets); the browser fills it here from the history and the URL, so
 * the entry runs and is tested without a device.
 */
import type { PairingLink } from "./pairing-link";

export type { PairingLink };

export type SafeAreaInsets = {
  top: number;
  right: number;
  bottom: number;
  left: number;
};

export interface MobilePlatform {
  /**
   * Registers the handler of system Back. It returns true when it went back one layer inside the app, and false when
   * it is at the root: the platform then leaves the app (or the browser leaves the page). Returns the unregister.
   */
  onBack(handler: () => boolean): () => void;
  /** The query string the app was launched with ("?view=task&id=..."), or "". */
  launchSearch(): string;
  /** A hint that arrives while the app runs (a widget tap on a warm app). Returns the unregister. */
  onLaunchSearch(listener: (search: string) => void): () => void;
  /**
   * The pairing link the app was launched with (`sidekick://pair?server=…&code=…`), if any. Absent on a platform that
   * has no links (the browser).
   */
  pairingLink?(): PairingLink | undefined;
  /** A pairing link that arrives while the app runs. Returns the unregister. */
  onPairingLink?(listener: (link: PairingLink) => void): () => void;
  /**
   * The app came back to the foreground (Android: `appStateChange` with isActive; browser: the tab became visible).
   * Returns the unregister.
   */
  onResume(listener: () => void): () => void;
  /** The system bar and cutout insets in CSS pixels. Undefined: the page uses the CSS env() values. */
  safeAreaInsets(): SafeAreaInsets | undefined;
}

/**
 * The browser's platform. Back is the history: one entry is pushed when the handler registers, so the browser's Back
 * button reaches the handler first, and a Back the handler declines goes on to leave the page.
 */
export function createWebPlatform(win: Window = window): MobilePlatform {
  return {
    onBack(handler) {
      win.history.pushState({ sidekickMobile: true }, "");
      const onPop = () => {
        if (handler()) win.history.pushState({ sidekickMobile: true }, "");
        else win.removeEventListener("popstate", onPop);
      };
      win.addEventListener("popstate", onPop);
      return () => win.removeEventListener("popstate", onPop);
    },
    launchSearch: () => win.location.search,
    onLaunchSearch: () => () => undefined,
    onResume(listener) {
      const onVisible = () => {
        if (win.document.visibilityState === "visible") listener();
      };
      win.document.addEventListener("visibilitychange", onVisible);
      return () =>
        win.document.removeEventListener("visibilitychange", onVisible);
    },
    safeAreaInsets: () => undefined,
  };
}
