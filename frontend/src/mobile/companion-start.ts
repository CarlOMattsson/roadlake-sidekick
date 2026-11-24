/**
 * Start and the suggestion inbox over the companion routes (ADR-005, ADR-013). Each tool the Start room asks for maps,
 * from this CLOSED list, to one named route; the answer is the tool's own structuredContent, so the room cannot tell
 * the difference. No generic execute, no path from the caller, no argument outside what the route takes.
 *
 *   get_start                -> GET  /companion/v1/start                         (no arguments)
 *   list_suggestions         -> GET  /companion/v1/suggestions                   (state, automation_id, group, limit, cursor)
 *   get_suggestion           -> GET  /companion/v1/suggestions/{suggestion_id}
 *   decide_suggestions       -> POST /companion/v1/suggestions/decisions         ({ items: 1-3 of { suggestion_id, expected_version, decision, confirmed? } })
 *   approve_suggestion_group -> POST /companion/v1/suggestions/group-approvals   ({ group_digest, suggestion_ids })
 *   undo_suggestion          -> POST /companion/v1/suggestions/{suggestion_id}/undo ({ expected_version })
 *
 * Deciding is the owner's act and needs the device capability `companion:suggestions:decide`; without it the server
 * answers 403 `forbidden`. The phone offers no edit of a card (`edits` is refused here, before anything is sent) and
 * no decision ticket (the group is approved by the device's own capability). Every write sends its key in the
 * Idempotency-Key header. Not in the app: the automation tools and skip_ready_conversation; the room hides what needs
 * them (`toolOffered`).
 */
import {
  isRecord,
  queryOf,
  withQuery,
  type Args,
  type PlanHelpers,
  type Planned,
} from "./companion-plan";

/** The routes, for reading and for the contract tests that compare them with the backend. Nothing is built from it. */
export const START_ROUTES = {
  get_start: { method: "GET", path: "/companion/v1/start" },
  list_suggestions: { method: "GET", path: "/companion/v1/suggestions" },
  get_suggestion: {
    method: "GET",
    path: "/companion/v1/suggestions/{suggestion_id}",
  },
  decide_suggestions: {
    method: "POST",
    path: "/companion/v1/suggestions/decisions",
  },
  approve_suggestion_group: {
    method: "POST",
    path: "/companion/v1/suggestions/group-approvals",
  },
  undo_suggestion: {
    method: "POST",
    path: "/companion/v1/suggestions/{suggestion_id}/undo",
  },
} as const;

/** The tool names this planner answers. */
export const START_TOOLS = [
  "get_start",
  "list_suggestions",
  "get_suggestion",
  "decide_suggestions",
  "approve_suggestion_group",
  "undo_suggestion",
] as const;

const BASE = "/companion/v1";
/** The most cards one decision call carries (the route refuses more). */
const MAX_DECISIONS = 3;
/** The most cards one group approval names (the size of a group). */
const MAX_GROUP = 25;
const DIGEST = /^[0-9a-f]{64}$/;

/** The planned call for a Start tool, or undefined when the name is not one of them. */
export function planStart(
  name: string,
  args: Args,
  h: PlanHelpers,
): Planned | undefined {
  /** A write: the signature is the action itself, so a retry of the same action sends the same key. */
  const write = (path: string, body: Args): Planned => {
    const signature = JSON.stringify([name, path, body]);
    return {
      request: {
        method: "POST",
        path,
        body,
        idempotencyKey: h.keyOf(args.idempotency_key, signature),
      },
      signature,
    };
  };

  switch (name) {
    case "get_start":
      h.onlyKeys(args, []);
      return { request: { method: "GET", path: `${BASE}/start` } };
    case "list_suggestions": {
      const query = queryOf(
        args,
        ["state", "automation_id", "group", "limit", "cursor"],
        [],
        [],
        h,
      );
      if (typeof query.automation_id === "string")
        query.automation_id = h.uuidOf(query.automation_id);
      return {
        request: {
          method: "GET",
          path: `${BASE}/suggestions`,
          ...withQuery(query),
        },
      };
    }
    case "get_suggestion":
      h.onlyKeys(args, ["suggestion_id"]);
      return {
        request: {
          method: "GET",
          path: `${BASE}/suggestions/${h.uuidOf(args.suggestion_id)}`,
        },
      };
    case "decide_suggestions": {
      h.onlyKeys(args, ["items", "idempotency_key"]);
      const items = args.items;
      if (
        !Array.isArray(items) ||
        items.length === 0 ||
        items.length > MAX_DECISIONS
      )
        return h.invalid();
      return write(`${BASE}/suggestions/decisions`, {
        items: items.map((item) => decisionOf(item, h)),
      });
    }
    case "approve_suggestion_group": {
      h.onlyKeys(args, ["group_digest", "suggestion_ids", "idempotency_key"]);
      const digest = args.group_digest;
      const ids = args.suggestion_ids;
      if (typeof digest !== "string" || !DIGEST.test(digest))
        return h.invalid();
      if (!Array.isArray(ids) || ids.length === 0 || ids.length > MAX_GROUP)
        return h.invalid();
      return write(`${BASE}/suggestions/group-approvals`, {
        group_digest: digest,
        suggestion_ids: ids.map((id) => h.uuidOf(id)),
      });
    }
    case "undo_suggestion": {
      h.onlyKeys(args, [
        "suggestion_id",
        "expected_version",
        "idempotency_key",
      ]);
      const id = h.uuidOf(args.suggestion_id);
      return write(`${BASE}/suggestions/${id}/undo`, {
        expected_version: h.versionOf(args.expected_version),
      });
    }
    default:
      return undefined;
  }
}

/** One card of a decision: approve or dismiss at a version. A card with `edits` is refused: the phone does not edit. */
function decisionOf(item: unknown, h: PlanHelpers): Args {
  if (!isRecord(item)) return h.invalid();
  h.onlyKeys(item, [
    "suggestion_id",
    "expected_version",
    "decision",
    "confirmed",
  ]);
  const { decision, confirmed } = item;
  if (decision !== "approve" && decision !== "dismiss") return h.invalid();
  if (confirmed !== undefined && typeof confirmed !== "boolean")
    return h.invalid();
  return {
    suggestion_id: h.uuidOf(item.suggestion_id),
    expected_version: h.versionOf(item.expected_version),
    decision,
    ...(confirmed === undefined ? {} : { confirmed }),
  };
}
