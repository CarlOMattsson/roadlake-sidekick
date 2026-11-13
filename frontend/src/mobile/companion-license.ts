/**
 * The license over the companion routes (see docs/decisions/log.md D-083: license terms). The phone reads the display state and saves a key through the same
 * closed shape as every other call; the key goes only in the body of the PUT and is never kept.
 *
 *   (read, not a tool)  -> GET /companion/v1/license                    (server-license.ts)
 *   set_license_key     -> PUT /companion/v1/license  ({ key })
 *
 * Both answer the display state (`state`, `licensee`, `kind`, `expires`, and `accepted` after a PUT).
 */
import type { Args, PlanHelpers, Planned } from "./companion-plan";

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const LICENSE_ROUTES = {
  get_license: { method: "GET", path: "/companion/v1/license" },
  set_license_key: { method: "PUT", path: "/companion/v1/license" },
} as const;

/** The tool names this planner answers. */
export const LICENSE_TOOLS = ["set_license_key"] as const;

/** A signed license key is text of a sensible length; anything else is refused before it is sent. */
const KEY_MAX = 8_192;

/** The planned call for the license tool, or undefined when the name is not it. */
export function planLicense(
  name: string,
  args: Args,
  h: PlanHelpers,
): Planned | undefined {
  if (name !== "set_license_key") return undefined;
  h.onlyKeys(args, ["key"]);
  const key = args.key;
  if (typeof key !== "string" || !key.trim() || key.length > KEY_MAX)
    return h.invalid();
  return {
    request: {
      method: "PUT",
      path: LICENSE_ROUTES.set_license_key.path,
      body: { key: key.trim() },
    },
  };
}
