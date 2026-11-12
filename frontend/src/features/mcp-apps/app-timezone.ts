/** The owner's IANA time zone, declared by the backend in the MCP app bootstrap. */
export const DEFAULT_OWNER_TIMEZONE = "Europe/Stockholm";

const OWNER_ZONE_META = "sidekick-owner-timezone";

let lastDeclared: string | undefined;
let resolved = DEFAULT_OWNER_TIMEZONE;

/** Missing or unsupported declarations use the default, independently of the host's zone. */
export function appTimeZone(doc: Document = document): string {
  const declared = doc.querySelector<HTMLMetaElement>(
    `meta[name="${OWNER_ZONE_META}"]`,
  )?.content;
  if (declared !== lastDeclared) {
    lastDeclared = declared;
    resolved = DEFAULT_OWNER_TIMEZONE;
    if (declared) {
      try {
        // Validate once per declaration; date formatters are built lazily by their callers.
        new Intl.DateTimeFormat("en", { timeZone: declared });
        resolved = declared;
      } catch {
        // An older host's ICU may not recognise a zone supported by the backend.
      }
    }
  }
  return resolved;
}

/**
 * Declares the owner's zone in the document, as the backend does in the app document. The phone has no such document,
 * so it writes the same meta from the zone the server told the device; `undefined` (the server never said) removes it,
 * and the default stands.
 */
export function declareOwnerTimeZone(
  zone: string | undefined,
  doc: Document = document,
): void {
  let meta = doc.querySelector<HTMLMetaElement>(
    `meta[name="${OWNER_ZONE_META}"]`,
  );
  if (zone === undefined) {
    meta?.remove();
    return;
  }
  if (!meta) {
    meta = doc.createElement("meta");
    meta.name = OWNER_ZONE_META;
    doc.head.append(meta);
  }
  meta.content = zone;
}

const formats = new Map<string, Intl.DateTimeFormat>();

/**
 * A formatter in the owner's zone, built on first use: the first Intl.DateTimeFormat of a page costs
 * tens of milliseconds, which the MCP App would otherwise pay before its first paint.
 */
export function ownerDateFormat(
  locale: string,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const timeZone = appTimeZone();
  const key = `${locale}|${timeZone}|${JSON.stringify(options)}`;
  let format = formats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, { ...options, timeZone });
    formats.set(key, format);
  }
  return format;
}

/**
 * When an offline copy was read, for "Ingen anslutning · senast hämtad 14:02": the time alone when the copy is from
 * today, else "11 nov. 14:02". The owner's clock, as every time in the apps reads.
 */
export function copyTime(at: number, locale: string): string {
  const when = new Date(at);
  const day = ownerDateFormat(locale, { dateStyle: "medium" });
  const sameDay = day.format(when) === day.format(new Date());
  return ownerDateFormat(
    locale,
    sameDay
      ? { hour: "2-digit", minute: "2-digit" }
      : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" },
  ).format(when);
}

/** `zone` when the host knows it, otherwise the declared owner zone. */
function resolveZone(zone?: string): string {
  if (zone) {
    try {
      new Intl.DateTimeFormat("en", { timeZone: zone });
      return zone;
    } catch {
      // An unknown zone name is ignored; the declared zone stands.
    }
  }
  return appTimeZone();
}

/**
 * Today's calendar date (YYYY-MM-DD) in the owner's zone, never the device's. `zone` is a zone the server named
 * in a result (the phone has no document meta); a missing or unsupported one falls back to the declared zone.
 */
export function ownerToday(zone?: string, now: Date = new Date()): string {
  const timeZone = resolveZone(zone);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/**
 * The instant 12:00 on the calendar day `day` (YYYY-MM-DD) strikes in the owner's zone (see `ownerToday` for
 * `zone`), as an ISO string, never in the device's zone: a device far from the owner would otherwise land the
 * entry on the neighbouring day. Malformed input yields undefined.
 */
export function ownerNoon(day: string, zone?: string): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return undefined;
  const wall = Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    12,
  );
  if (Number.isNaN(wall)) return undefined;
  const clock = new Intl.DateTimeFormat("en-CA", {
    timeZone: resolveZone(zone),
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  const offsetAt = (instant: number): number => {
    const parts = clock.formatToParts(new Date(instant));
    const part = (type: string): number =>
      Number(parts.find((p) => p.type === type)?.value);
    const shown = Date.UTC(
      part("year"),
      part("month") - 1,
      part("day"),
      part("hour"),
      part("minute"),
    );
    return shown - Math.floor(instant / 60_000) * 60_000;
  };
  // Two passes settle the offset at the instant itself, not at the wall time read as UTC.
  let instant = wall - offsetAt(wall);
  instant = wall - offsetAt(instant);
  return new Date(instant).toISOString();
}
