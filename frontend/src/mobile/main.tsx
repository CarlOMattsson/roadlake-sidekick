/**
 * The mobile entry (frontend/mobile.html): the same rooms as the Claude app, over the companion transport.
 * Built to frontend/dist-mobile by `npm run build:mobile`, separately from the MCP App bundle, and packaged inside the
 * Android app (Capacitor, android/). In the Android app the platform is the native one (Back, launch hints, insets); in
 * a browser it is the web platform and the plugin's web stand-in, which is never paired.
 */
import "./base.css";
import "@/features/mcp-apps/ui/tokens.css";
import "@/features/mcp-apps/ui/family.css";
import "./mobile.css";
import { Capacitor } from "@capacitor/core";
import { useState } from "react";
import { createRoot } from "react-dom/client";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import {
  RenderErrorBoundary,
  StartupError,
} from "@/features/mcp-apps/ui/error-boundary";
import { SidekickNative } from "./sidekick-native";
import { CompanionRoomTransport } from "./companion-transport";
import { chooseAppLanguage, startAppLanguage } from "./app-language";
import { MobileApp } from "./mobile-app";
import { PairingGate } from "./pairing-gate";
import { createWebPlatform, type MobilePlatform } from "./platform";

// The class scopes mobile.css to this app; the MCP App bundle never sets it.
document.documentElement.classList.add("sk-mobile");

// The owner's choice of language when there is one, else the bundle's (Swedish by default); see app-language.ts.
const startLocale = startAppLanguage();

async function platform(): Promise<MobilePlatform> {
  if (!Capacitor.isNativePlatform()) return createWebPlatform();
  return (await import("./platform-native")).createNativePlatform();
}

// The pairing screen speaks the app's language (Swedish by default), like the rest of the app and the widget; the phone's
// own language is not used.
const root = createRoot(document.getElementById("root")!);

/**
 * The app in the chosen language. A new choice (the pairing screen's switch, Inställningar) is declared first, so every
 * room that reads `appLocale()` draws in it, and then the tree is drawn again in it; the pairing and the open
 * settings stay.
 */
function LocalizedApp({ platform }: { platform: MobilePlatform }) {
  const [locale, setLocale] = useState<AppLocale>(startLocale);
  const choose = (next: AppLocale) => {
    chooseAppLanguage(next);
    setLocale(next);
  };
  return (
    <RenderErrorBoundary locale={locale} scope="app">
      <PairingGate
        native={SidekickNative}
        platform={platform}
        locale={locale}
        onLocale={choose}
      >
        <MobileApp
          transport={transport}
          platform={platform}
          locale={locale}
          native={SidekickNative}
          onLocale={choose}
        />
      </PairingGate>
    </RenderErrorBoundary>
  );
}

// One transport for the app's life, so a change of language keeps what it holds.
const transport = new CompanionRoomTransport(SidekickNative);

/** Loads the platform and draws the app; a failure shows a short translated card with `retry`, never the error. */
function start() {
  platform()
    .then((mobilePlatform) => {
      root.render(<LocalizedApp platform={mobilePlatform} />);
    })
    .catch((error: unknown) => {
      console.error("[sidekick] start failed", {
        kind: error instanceof Error ? error.name : "unknown",
      });
      root.render(<StartupError locale={startLocale} onRetry={start} />);
    });
}

start();
