import { useEffect } from "react";

import { applyHostStyle } from "@/features/mcp-apps/host-style";
import type { MobilePlatform } from "./platform";

const SIDES = ["top", "right", "bottom", "left"] as const;

/**
 * Publishes the safe-area insets as the `--host-safe-*` variables the room frames read. The platform's numbers when it
 * has them; otherwise the WebView's own: `env(safe-area-inset-*)` (set by the WebView with `viewport-fit=cover`) and
 * Capacitor's `--safe-area-inset-*` (injected by its SystemBars plugin, which also removes the keyboard's height from
 * the bottom while the keyboard is up). The larger of the two wins, so a WebView that supplies both is not counted twice.
 */
export function useSafeAreaInsets(platform: MobilePlatform): void {
  useEffect(() => {
    const root = document.documentElement;
    const insets = platform.safeAreaInsets();
    if (insets) {
      applyHostStyle({ safeAreaInsets: insets }, root);
      return;
    }
    for (const side of SIDES)
      root.style.setProperty(
        `--host-safe-${side}`,
        `max(env(safe-area-inset-${side}, 0px), var(--safe-area-inset-${side}, 0px))`,
      );
  }, [platform]);
}
