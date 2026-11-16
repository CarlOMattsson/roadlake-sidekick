import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import { useSingleFlight } from "../shared/use-single-flight";
import {
  writeFailure,
  type WorkAiPlan,
  type WorkAiPlanStep,
  type WorkTask,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";

export type AiPlanPhase = "loading" | "ready" | "error";
/** The approval click: what it last did. A failure keeps its closed reason; `conflict` means the digest was stale. */
export type AiApproval = "idle" | "busy" | "approved" | WriteFailure;

/**
 * A Task's plan for AI steps, read while the Task is marked as possible with AI and the host answers get_ai_plan. The
 * plan is read again when the Task's version moves (an edit can change what the owner approves), when a run is
 * reviewed, and on Try again; a re-read keeps the plan on screen until the answer comes. `approve` sends exactly the
 * digest the view shows; a retry of the same click keeps its key.
 */
export function useAiPlan(
  transport: WorkTransport,
  task: WorkTask | undefined,
) {
  const offers = useToolSupport(transport);
  const shown = Boolean(task?.ai_possible) && offers("get_ai_plan");
  const taskId = task?.id;
  const [plan, setPlan] = useState<WorkAiPlan>();
  const [phase, setPhase] = useState<AiPlanPhase>("loading");
  const [readError, setReadError] = useState<unknown>();
  const [reads, setReads] = useState(0);
  const [approval, setApproval] = useState<AiApproval>("idle");
  // Bumped after a verdict on a run: the Step list is read again in place.
  const [stepsKey, setStepsKey] = useState(0);
  const mounted = useMounted();
  const flight = useSingleFlight();
  const pending = useRef<PendingKey | undefined>(undefined);
  const ticket = useRef(0);

  useEffect(() => {
    if (!shown || !taskId) return;
    const taken = ++ticket.current;
    transport.getAiPlan(taskId).then(
      (result) => {
        if (taken !== ticket.current || !mounted.current) return;
        setPlan(result.plan);
        setPhase("ready");
      },
      (error: unknown) => {
        if (taken !== ticket.current || !mounted.current) return;
        setReadError(error);
        setPhase("error");
      },
    );
  }, [shown, taskId, task?.version, reads, transport, mounted]);

  const reload = useCallback(() => setReads((n) => n + 1), []);
  const retry = useCallback(() => {
    setPhase("loading");
    setReads((n) => n + 1);
  }, []);

  function approve() {
    if (!plan || !flight.enter()) return;
    const claimed = keyFor(
      pending.current,
      JSON.stringify([plan.task_id, plan.digest]),
    );
    pending.current = claimed;
    setApproval("busy");
    transport
      .approveAiPlan(plan.task_id, plan.digest, claimed.key)
      .then(
        (result) => {
          pending.current = undefined;
          if (!mounted.current) return;
          setPlan(result.plan);
          setApproval("approved");
        },
        (error: unknown) => {
          if (mounted.current) setApproval(writeFailure(error));
        },
      )
      .finally(() => flight.leave());
  }

  /**
   * After a verdict on a run the plan and the Steps are read again: an accepted result completed the Step, and every
   * verdict moved the Step's AI state.
   */
  const reviewed = useCallback(() => {
    setReads((n) => n + 1);
    setStepsKey((n) => n + 1);
  }, []);

  /** A conflict on approve: the plan is read again and the click starts over with a new key. */
  function reloadAfterConflict() {
    pending.current = undefined;
    setApproval("idle");
    reload();
  }

  const byStep = useMemo(() => {
    const steps = new Map<string, WorkAiPlanStep>();
    for (const entry of plan?.steps ?? []) steps.set(entry.step.id, entry);
    return steps;
  }, [plan]);

  return {
    shown,
    phase,
    plan: shown ? plan : undefined,
    readError,
    retry,
    approval,
    approve,
    reloadAfterConflict,
    reviewed,
    byStep,
    stepsKey,
  };
}
export type AiPlanState = ReturnType<typeof useAiPlan>;
