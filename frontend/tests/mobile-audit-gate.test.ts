import { afterEach, describe, expect, it } from "vitest";
import {
  assertAuditClean,
  unexpectedAuditErrors,
} from "./e2e/mobile-audit-gate";

const clean = {
  id: "x__390__light",
  stepError: null,
  probeError: null,
  measured: { horizontal: false },
  failures: [],
};

afterEach(() => {
  delete process.env.MOBILE_AUDIT_LENIENT;
});

describe("mobile audit gate", () => {
  it("accepts a clean outcome", () => {
    expect(unexpectedAuditErrors(clean)).toEqual([]);
    expect(() => assertAuditClean(clean)).not.toThrow();
  });

  it("blocks step, probe, measurement and page errors with a clear message", () => {
    const bad = {
      ...clean,
      stepError: "Error: click timed out",
      probeError: "Error: probe",
      measured: { error: "evaluate failed" },
      failures: ["pageerror: boom"],
    };
    expect(unexpectedAuditErrors(bad)).toHaveLength(4);
    expect(() => assertAuditClean(bad)).toThrow(
      /x__390__light hit unexpected errors[\s\S]*step error[\s\S]*page error/,
    );
  });

  it("treats missing measurement data as an error", () => {
    expect(unexpectedAuditErrors({ ...clean, measured: null })).toEqual([
      "measurement returned no data",
    ]);
  });

  it("lets MOBILE_AUDIT_LENIENT=1 keep measure-only mode", () => {
    process.env.MOBILE_AUDIT_LENIENT = "1";
    expect(() => assertAuditClean({ ...clean, stepError: "x" })).not.toThrow();
  });
});
