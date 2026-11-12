/**
 * The checks of the pairing form, made on the phone before anything is sent. They mirror what the native side and the
 * server accept (`ServerUrl.kt`: an origin and nothing after it, https; `CompanionClient.PAIRING_SECRET`: 16 to 128
 * letters, digits, `_` and `-`), so a mistake is shown by the field it is in, not after a round trip. The native side
 * still decides: these checks only spare the user a trip.
 */

export type ServerProblem = "required" | "invalid";
export type CodeProblem = "required" | "short" | "invalid";

/** Reachable only from the same machine; http is allowed for these (the debug build). Same set as ServerUrl.kt. */
const LOCAL_HOSTS = new Set(["10.0.2.2", "localhost", "127.0.0.1"]);

const CODE_MIN = 16;
const CODE_MAX = 128;
const CODE_CHARS = /^[A-Za-z0-9_-]+$/;

/** "sidekick.example" becomes "https://sidekick.example"; an address with a scheme is left as typed. */
export function withScheme(address: string): string {
  const text = address.trim();
  return text === "" || text.includes("://") ? text : `https://${text}`;
}

/** What is wrong with the typed server address, or undefined when it can go to the phone's own check. */
export function serverProblem(address: string): ServerProblem | undefined {
  if (address.trim() === "") return "required";
  let url: URL;
  try {
    url = new URL(withScheme(address));
  } catch {
    return "invalid";
  }
  const local = LOCAL_HOSTS.has(url.hostname);
  const secure =
    url.protocol === "https:" || (url.protocol === "http:" && local);
  const origin =
    url.username === "" &&
    url.password === "" &&
    url.pathname === "/" &&
    url.search === "" &&
    url.hash === "";
  // Like the native side: a name without a dot ("sidekick", "nas:8443") is a valid internal host.
  return secure && origin ? undefined : "invalid";
}

/** What is wrong with the typed pairing code, or undefined. */
export function codeProblem(code: string): CodeProblem | undefined {
  const text = code.trim();
  if (text === "") return "required";
  if (!CODE_CHARS.test(text) || text.length > CODE_MAX) return "invalid";
  return text.length < CODE_MIN ? "short" : undefined;
}

/** The host shown when the user is asked to confirm, or "" for an address that does not parse. */
export function hostOf(address: string): string {
  try {
    return new URL(withScheme(address)).host;
  } catch {
    return "";
  }
}
