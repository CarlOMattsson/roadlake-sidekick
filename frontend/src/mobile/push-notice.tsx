/**
 * The calm note of the mobile app when push cannot work because no UnifiedPush distributor (the ntfy app) is
 * installed. Everything else keeps working: Today is read in the foreground and by the widget's schedule. The note
 * is drawn only when the server sends notifications at all (`pushEnabled` of the pairing: a server with push off has
 * nothing for ntfy to bring) and the distributor is missing; a denied notification permission or a registration
 * the server has not accepted yet is not the owner's to fix with this line. A refused or failed read draws nothing.
 * "Inte nu" puts it away for good on this phone; Inställningar keep the same fix.
 */
import { useEffect, useState } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import { Button } from "@/features/mcp-apps/ui/button";
import type { SidekickNativePlugin, PushStatus } from "./sidekick-native";
import "./push-notice.css";

export type PushNoticeLabels = {
  /** The sentence beside the note. Ends with a full stop (designsystem §1.6). */
  missing: string;
  /** The button that opens ntfy's page in the app store. */
  install: string;
  /** Puts the note away on this phone (Inställningar keep the fix). */
  dismiss: string;
};

export const pushNoticeLabelsSv: PushNoticeLabels = {
  missing: "Installera ntfy för aviseringar.",
  install: "Hämta ntfy",
  dismiss: "Inte nu",
};

export const pushNoticeLabelsEn: PushNoticeLabels = {
  missing: "Install ntfy for notifications.",
  install: "Get ntfy",
  dismiss: "Not now",
};

export function pushNoticeLabelsFor(locale: AppLocale): PushNoticeLabels {
  return locale === "en" ? pushNoticeLabelsEn : pushNoticeLabelsSv;
}

/** Where "Inte nu" is kept: in the page's own storage, so it outlives a restart and goes with the app's data. */
export const PUSH_NOTICE_DISMISSED_KEY = "sidekick.pushNotice.dismissed";

function dismissedBefore(): boolean {
  try {
    return localStorage.getItem(PUSH_NOTICE_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

export type PushNoticeProps = {
  native: Pick<
    SidekickNativePlugin,
    "pushStatus" | "deviceStatus" | "openNtfyInstall"
  >;
  locale: AppLocale;
  /** Changes when the app comes back to the foreground: ntfy may have been installed meanwhile. */
  refreshKey: number;
};

export function PushNotice({ native, locale, refreshKey }: PushNoticeProps) {
  const [status, setStatus] = useState<PushStatus | undefined>();
  const [serverPush, setServerPush] = useState(false);
  const [dismissed, setDismissed] = useState(dismissedBefore);

  useEffect(() => {
    if (dismissed) return undefined;
    let live = true;
    Promise.all([native.pushStatus(), native.deviceStatus()]).then(
      ([next, device]) => {
        if (!live) return;
        setStatus(next);
        setServerPush(device.pushEnabled === true);
      },
      () => {
        if (live) setStatus(undefined);
      },
    );
    return () => {
      live = false;
    };
  }, [native, refreshKey, dismissed]);

  if (dismissed || !serverPush || !status || status.distributor) return null;
  const labels = pushNoticeLabelsFor(locale);
  return (
    <div className="mobile-push-notice" lang={locale}>
      <p role="status" className="mobile-push-notice__text">
        {labels.missing}
      </p>
      <div className="mobile-push-notice__actions">
        <Button
          variant="quiet"
          onClick={() => {
            // A store that cannot open leaves the note as it is; the state is read again when the app comes back.
            native.openNtfyInstall().catch(() => undefined);
          }}
        >
          {labels.install}
        </Button>
        <Button
          variant="quiet"
          className="mobile-push-notice__dismiss"
          onClick={() => {
            try {
              localStorage.setItem(PUSH_NOTICE_DISMISSED_KEY, "1");
            } catch {
              // Without storage the note is put away for this run only.
            }
            setDismissed(true);
          }}
        >
          {labels.dismiss}
        </Button>
      </div>
    </div>
  );
}
