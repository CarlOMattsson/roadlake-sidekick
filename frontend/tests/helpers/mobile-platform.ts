import type { MobilePlatform } from "@/mobile/platform";

/** A simulated phone platform (no native shell): system Back is pressed with `pressBack`, which the app's handler takes. */
export function simulatedPlatform(): MobilePlatform & {
  pressBack: () => boolean;
} {
  let back: (() => boolean) | undefined;
  return {
    onBack: (handler) => {
      back = handler;
      // Like the native stack: leaving removes only what this call registered.
      return () => {
        if (back === handler) back = undefined;
      };
    },
    launchSearch: () => "",
    onLaunchSearch: () => () => undefined,
    onResume: () => () => undefined,
    safeAreaInsets: () => undefined,
    pressBack: () => back?.() ?? false,
  };
}
