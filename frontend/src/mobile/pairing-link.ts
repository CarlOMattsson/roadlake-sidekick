/**
 * The pairing link the server's pairing command prints: `sidekick://pair?server=<url>&code=<code>`. Opening it on the
 * phone fills in the pairing form; it never pairs by itself (the gate asks first), because any app or web page can
 * open such a link. Like the launch hint (`launch-hint.ts`) it is only a hint: anything unexpected is no link.
 */
import { codeProblem, serverProblem } from "./pairing-validation";

export type PairingLink = { serverUrl: string; code: string };

const PREFIX = "sidekick://pair?";
const MAX_LENGTH = 1024;

/** The link in `url`, or undefined for any other URL, a repeated or missing field, or values the form would refuse. */
export function parsePairingLink(
  url: string | null | undefined,
): PairingLink | undefined {
  if (typeof url !== "string" || url.length > MAX_LENGTH) return undefined;
  if (!url.startsWith(PREFIX)) return undefined;
  const fragment = url.indexOf("#");
  const query = url.slice(
    PREFIX.length,
    fragment === -1 ? undefined : fragment,
  );
  const params = new URLSearchParams(query);
  const servers = params.getAll("server");
  const codes = params.getAll("code");
  if (servers.length !== 1 || codes.length !== 1) return undefined;
  const serverUrl = servers[0]?.trim() ?? "";
  const code = codes[0]?.trim() ?? "";
  if (serverProblem(serverUrl) || codeProblem(code)) return undefined;
  return { serverUrl, code };
}
