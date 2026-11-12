import type { CapacitorConfig } from "@capacitor/cli";

/**
 * The Capacitor shell of the Android app (ADR-005). The web assets are the mobile bundle built by
 * `npm run build:mobile`, packaged inside the app: no `server.url`, so no remote page is ever loaded into the WebView.
 *
 * The application id here is the base id. Gradle's debug build type adds the suffix ".debug"
 * (com.roadlake.sidekick.debug), so a debug build installs next to a build with the base id.
 */
const config: CapacitorConfig = {
  appId: "com.roadlake.sidekick",
  appName: "Sidekick",
  webDir: "dist-mobile",
  // Nothing from the bridge or the plugins goes to Logcat: a title or a token must never reach a log (ADR-005).
  loggingBehavior: "none",
  android: {
    // The same floor as the mobile bundle's build target (vite.mobile.config.ts) and WebViewRequirement.kt, which shows
    // an explanation instead of loading the page when the installed WebView is older.
    minWebViewVersion: 123,
    // No remote content, no mixed content, no debugging of release builds.
    allowMixedContent: false,
    webContentsDebuggingEnabled: false,
  },
  plugins: {
    // Edge-to-edge: the page draws under the system bars and gets the bar sizes as CSS variables
    // (--safe-area-inset-*); SystemBars also pads the window by the keyboard height, so a focused field is never
    // covered. (The separate Keyboard plugin is not used: it is the pre-edge-to-edge way and SystemBars warns
    // against combining them.)
    SystemBars: { insetsHandling: "css", initialViewportFitValueHint: "cover" },
  },
};

export default config;
