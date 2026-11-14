import { useSyncExternalStore } from "react";

import { isPlainObject } from "../../lib/mcp/shape";
import { parseDueDay } from "./ui/due";

/**
 * The license signal (see docs/decisions/log.md D-083: license terms). The backend writes the display state
 * into the app document, next to `sidekick-rooms` and the build metas, as one JSON meta:
 * `<meta name="sidekick-license" content='{"state":"unlicensed","licensee":"…","kind":"personal","expires":"2027-11-09"}'>`.
 * Only `state` is required. The key itself is never in the document. The phone has no such document: it reads the
 * same object from the companion route and declares it here (`declareLicense`), as it does the rooms.
 *
 * No meta (an older server, or a host that does not say) means nothing at all is drawn: no coin and no row.
 * `invalid` is shown as `unlicensed`. A license whose `expires` has passed on this device's clock counts as expired,
 * so the signal comes back offline too.
 */
export type LicenseState = "unlicensed" | "licensed" | "expired";

export type License = {
  state: LicenseState;
  /** The name the license is issued to ("Alex Exempel", "Example AB"). */
  licensee?: string;
  kind?: "personal" | "org";
  /** The last day the license holds, YYYY-MM-DD. */
  expires?: string;
};

/**
 * Where `buy` leads: the one place to set the shop address once there is one. While it is empty no button is
 * drawn and the row says that keys are on sale soon instead (`buySoon`); docs/explanation/licensing.md and .sv.md name the same
 * address under "How to buy".
 */
export const LICENSE_BUY_URL = "";

const META = "sidekick-license";
const CHANGED = "sidekick:license";
const MENU = "sidekick:license-menu";
const DATE = /^\d{4}-\d{2}-\d{2}$/;
/** A focus request older than this is forgotten, so a row mounted much later does not take the focus. */
const FOCUS_WINDOW_MS = 2_000;

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/**
 * The display state in `value` (the meta's object, a tool result or a companion answer), or undefined when it names no
 * state Sidekick knows. `invalid` becomes `unlicensed`.
 */
export function licenseFrom(value: unknown): License | undefined {
  if (!isPlainObject(value)) return undefined;
  const raw = value.state;
  const state = raw === "invalid" ? "unlicensed" : raw;
  if (state !== "unlicensed" && state !== "licensed" && state !== "expired")
    return undefined;
  const license: License = { state };
  const licensee = text(value.licensee);
  if (licensee) license.licensee = licensee;
  if (value.kind === "personal" || value.kind === "org")
    license.kind = value.kind;
  if (typeof value.expires === "string" && DATE.test(value.expires))
    license.expires = value.expires;
  return license;
}

/** The meta's content as written, or undefined without a meta. */
function declaredContent(doc: Document = document): string | undefined {
  return doc.querySelector<HTMLMetaElement>(`meta[name="${META}"]`)?.content;
}

/** The display state the content of the meta names, or undefined (no meta, not JSON, unknown state). */
export function parseLicenseMeta(
  content: string | undefined,
): License | undefined {
  if (content === undefined) return undefined;
  try {
    return licenseFrom(JSON.parse(content));
  } catch {
    return undefined;
  }
}

/** The license the document declares, before the clock is applied. */
export function readLicense(doc: Document = document): License | undefined {
  return parseLicenseMeta(declaredContent(doc));
}

/** The day `instant` falls on in the owner zone, as parseDueDay counts days. */
function dayOf(instant: Date): number | null {
  return Number.isNaN(instant.getTime())
    ? null
    : parseDueDay(instant.toISOString());
}

/** A licensed state whose last day has passed on this clock is expired. Everything else is as declared. */
export function licenseAt(
  license: License | undefined,
  now: Date,
): License | undefined {
  if (license?.state !== "licensed" || !license.expires) return license;
  const last = parseDueDay(license.expires);
  const today = dayOf(now);
  if (last === null || today === null || today <= last) return license;
  return { ...license, state: "expired" };
}

/** Whether the coin stands: free version, or the license ran out. */
export function licenseSignals(license: License | undefined): boolean {
  return license?.state === "unlicensed" || license?.state === "expired";
}

/**
 * Declares the display state in the document, as the backend does in the app document, and tells every coin and row
 * of the page. The phone writes it from the companion route; a saved key writes the answer of set_license_key.
 * `undefined` removes the meta: nothing is drawn.
 */
export function declareLicense(
  license: License | undefined,
  doc: Document = document,
): void {
  let meta = doc.querySelector<HTMLMetaElement>(`meta[name="${META}"]`);
  if (license === undefined) meta?.remove();
  else {
    if (!meta) {
      meta = doc.createElement("meta");
      meta.name = META;
      doc.head.append(meta);
    }
    meta.content = JSON.stringify(license);
  }
  doc.defaultView?.dispatchEvent(new Event(CHANGED));
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGED, onChange);
  return () => window.removeEventListener(CHANGED, onChange);
}

function snapshot(): string {
  return declaredContent() ?? "";
}

/**
 * The license to show now, on this device's clock, or undefined (nothing is drawn). Follows `declareLicense` at once.
 * `now` is the clock; tests pass a fixed one.
 */
export function useLicense(
  now: () => Date = () => new Date(),
): License | undefined {
  const content = useSyncExternalStore(subscribe, snapshot);
  if (!content) return undefined;
  return licenseAt(parseLicenseMeta(content), now());
}

// ---- Where the coin leads. The shell (or a card) asks; the place that holds the row opens and the row takes the focus.

let focusAskedAt = 0;

/** The next license row that is shown takes the focus (Control, a ⋯ panel or the phone's settings). */
export function requestLicenseFocus(): void {
  focusAskedAt = Date.now();
}

/** Whether a row should take the focus now; the request is spent. */
export function takeLicenseFocus(): boolean {
  const asked = focusAskedAt > 0 && Date.now() - focusAskedAt < FOCUS_WINDOW_MS;
  focusAskedAt = 0;
  return asked;
}

/** Whether a focus request stands, without spending it. */
export function licenseFocusAsked(): boolean {
  return focusAskedAt > 0 && Date.now() - focusAskedAt < FOCUS_WINDOW_MS;
}

/**
 * Asks the ⋯ menu of the room on screen to open on its license row (Control is off). True when a menu answered;
 * false when none did (the view on screen has no ⋯), and the caller shows the row itself.
 */
export function openLicenseMenu(): boolean {
  const event = new Event(MENU, { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

/** For the ⋯ owners: `open` runs when the coin asks, and returns true when this menu opened. */
export function onLicenseMenu(open: () => boolean): () => void {
  const listener = (event: Event) => {
    if (!event.defaultPrevented && open()) event.preventDefault();
  };
  window.addEventListener(MENU, listener);
  return () => window.removeEventListener(MENU, listener);
}
