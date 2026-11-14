/**
 * The closed error codes of the MCP host and how the apps read them. One copy for every
 * transport (work, journal, control, shopping, companion), so a refusal means the same thing in
 * every app. Only the closed code is read, never backend text.
 */

/**
 * The codes the backend returns for a failed tool call (`_ERROR_MESSAGES` in
 * `backend/src/sidekick/mcp/results.py`).
 */
export type McpErrorCode =
  | "unauthorized"
  | "forbidden"
  | "validation_error"
  | "not_found"
  | "conflict"
  | "idempotency_conflict"
  | "unavailable"
  | "internal_error";

/** The extra codes of the companion HTTP envelope, which has its own bad_request and method refusals. */
export type CompanionErrorCode =
  McpErrorCode | "bad_request" | "method_not_allowed";

/** The closed error code a failure carries, or undefined when it carries none. */
export function errorCode(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | null | undefined)?.code;
  return typeof code === "string" ? code : undefined;
}

/**
 * True when the server refused this read for the current token (no permission for the
 * resource). Such a refusal is not transient, so a view shows calm copy instead of retry.
 */
export function isForbidden(error: unknown): boolean {
  return errorCode(error) === "forbidden";
}

/** True when the server refused with the closed code not_found: the record is gone. */
export function isNotFound(error: unknown): boolean {
  return errorCode(error) === "not_found";
}

/** True when a write was refused because the stored version moved on (the code conflict). */
export function isConflict(error: unknown): boolean {
  return errorCode(error) === "conflict";
}

/**
 * How a write was refused: `conflict` means the version the view holds is stale, `forbidden`
 * means no permission, `invalid` means the values were refused and `not_found` means the record
 * no longer exists (for example it was removed in another chat). None of these is retried;
 * anything else is `failed`, a transient failure that may be retried.
 */
export type WriteFailure =
  "conflict" | "forbidden" | "invalid" | "not_found" | "failed";

export function writeFailure(error: unknown): WriteFailure {
  switch (errorCode(error)) {
    case "conflict":
      return "conflict";
    case "forbidden":
      return "forbidden";
    // validation_error, bad_request, method_not_allowed: the server refused this request for good
    // (companion envelope included); sending the same request again cannot help.
    case "validation_error":
    case "bad_request":
    case "method_not_allowed":
      return "invalid";
    // not_found: the record is gone; sending the same write again cannot bring it back.
    case "not_found":
      return "not_found";
    default:
      return "failed";
  }
}
