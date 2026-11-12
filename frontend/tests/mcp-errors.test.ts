import { describe, expect, it } from "vitest";
import {
  errorCode,
  isConflict,
  isForbidden,
  isNotFound,
  writeFailure,
  type McpErrorCode,
} from "../src/lib/mcp/errors";
import * as journal from "../src/features/journal-app/transport";
import * as work from "../src/features/work-app/transport";
import * as control from "../src/features/control-app/transport";

const failed = (code: unknown) => ({ code });

describe("MCP error helpers", () => {
  it("reads only a string code", () => {
    expect(errorCode(failed("not_found"))).toBe("not_found");
    expect(errorCode(failed(404))).toBeUndefined();
    expect(errorCode(null)).toBeUndefined();
    expect(errorCode(undefined)).toBeUndefined();
    expect(errorCode("forbidden")).toBeUndefined();
    expect(errorCode(new Error("forbidden"))).toBeUndefined();
  });

  it("recognises forbidden, not_found and conflict by code only", () => {
    expect(isForbidden(failed("forbidden"))).toBe(true);
    expect(isForbidden(failed("not_found"))).toBe(false);
    expect(isNotFound(failed("not_found"))).toBe(true);
    expect(isNotFound(failed("forbidden"))).toBe(false);
    expect(isConflict(failed("conflict"))).toBe(true);
    expect(isConflict({ status: 409 })).toBe(false);
    expect(isForbidden(null)).toBe(false);
  });

  it("maps every code the backend returns to a write failure", () => {
    const expected: Record<McpErrorCode, string> = {
      unauthorized: "failed",
      forbidden: "forbidden",
      validation_error: "invalid",
      not_found: "not_found",
      conflict: "conflict",
      idempotency_conflict: "failed",
      unavailable: "failed",
      internal_error: "failed",
    };
    for (const [code, how] of Object.entries(expected)) {
      expect(writeFailure(failed(code))).toBe(how);
    }
    // The companion envelope's definitive refusals are not transient either.
    expect(writeFailure(failed("bad_request"))).toBe("invalid");
    expect(writeFailure(failed("method_not_allowed"))).toBe("invalid");
    expect(writeFailure(new Error("boom"))).toBe("failed");
    expect(writeFailure(undefined)).toBe("failed");
  });

  it("is the one copy every transport exports", () => {
    expect(work.writeFailure).toBe(writeFailure);
    expect(journal.writeFailure).toBe(writeFailure);
    expect(control.writeFailure).toBe(writeFailure);
    expect(work.isForbidden).toBe(isForbidden);
    expect(journal.isForbidden).toBe(isForbidden);
    expect(journal.writeFailure(failed("not_found"))).toBe("not_found");
  });
});
