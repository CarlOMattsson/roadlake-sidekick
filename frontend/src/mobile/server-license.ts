/**
 * The license display state, for the phone (see docs/decisions/log.md D-083). Claude's app document carries it as a meta; the phone has no such
 * document, so it reads `GET /companion/v1/license` at the start and on every return to the foreground and declares the
 * answer the way the backend does (license-state.ts), so the coin and the row read one answer. A server that has no
 * route (older: 404) or answers nothing Sidekick knows removes the declaration: nothing is drawn. No answer at all (no
 * network) keeps what was declared.
 */
import { useEffect } from "react";

import { declareLicense, licenseFrom } from "@/features/mcp-apps/license-state";
import type { SidekickNativePlugin } from "./sidekick-native";
import { isRecord } from "./companion-plan";
import { LICENSE_ROUTES } from "./companion-license";

export type ServerLicenseNative = Partial<
  Pick<SidekickNativePlugin, "request">
>;

export function useServerLicense(
  native: ServerLicenseNative | undefined,
  refreshKey: number,
): void {
  useEffect(() => {
    const request = native?.request?.bind(native);
    if (!request) return undefined;
    let live = true;
    request({ method: "GET", path: LICENSE_ROUTES.get_license.path }).then(
      ({ status, body }) => {
        if (!live) return;
        if (status < 200 || status >= 300) {
          // The server said no (an older one has no route): nothing is drawn. A 5xx keeps what was there.
          if (status < 500) declareLicense(undefined);
          return;
        }
        const display = isRecord(body)
          ? licenseFrom(isRecord(body.license) ? body.license : body)
          : undefined;
        declareLicense(display);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [native, refreshKey]);

  // The declaration belongs to this pairing: it goes with the app.
  useEffect(() => () => declareLicense(undefined), []);
}
