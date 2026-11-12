// Quality gate for the mobile audit: a scenario that hits a step, probe, measurement or page error
// must fail the test (blocking). The metrics JSON is still written first so the evidence survives.
// Set MOBILE_AUDIT_LENIENT=1 to only measure (old behaviour) while debugging.
export type AuditOutcome = {
  id: string;
  stepError: string | null;
  probeError: string | null;
  measured: unknown;
  failures: readonly unknown[];
};

export function unexpectedAuditErrors(outcome: AuditOutcome): string[] {
  const errors: string[] = [];
  if (outcome.stepError) errors.push(`step error: ${outcome.stepError}`);
  if (outcome.probeError) errors.push(`probe error: ${outcome.probeError}`);
  const measured = outcome.measured as { error?: string } | null;
  if (measured === null || typeof measured !== "object")
    errors.push("measurement returned no data");
  else if (measured.error) errors.push(`measurement error: ${measured.error}`);
  for (const failure of outcome.failures)
    errors.push(`page error: ${String(failure)}`);
  return errors;
}

export function assertAuditClean(outcome: AuditOutcome): void {
  if (process.env.MOBILE_AUDIT_LENIENT === "1") return;
  const errors = unexpectedAuditErrors(outcome);
  if (errors.length > 0)
    throw new Error(
      `Mobile audit ${outcome.id} hit unexpected errors:\n- ${errors.join("\n- ")}`,
    );
}
