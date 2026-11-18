import { useRef, useState } from "react";
import { errorReason } from "../../../lib/mcp/errors";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import { useSingleFlight } from "../shared/use-single-flight";
import {
  writeFailure,
  type WorkAiPlan,
  type WorkAiPlanStep,
  type WorkAiRun,
  type WorkTransport,
} from "../transport/transport";

type Run = WorkAiRun["run"];

/** Why the server did not queue the Step: a closed reason it gave, or the kind of refusal. */
export type RunRefusal =
  | "ai_budget_reached"
  | "ai_limit_reached"
  | "ai_runner_off"
  | "invalid"
  | "forbidden"
  | "failed";
const REASONS = new Set<string>([
  "ai_budget_reached",
  "ai_limit_reached",
  "ai_runner_off",
]);

/** A run the server holds and the owner may stop: queued, or taken and under way. */
export function serverRunActive(run: Run | null | undefined): run is Run {
  return (
    run?.runner === "server" &&
    (run.state === "queued" || run.state === "running")
  );
}

/**
 * The Step "Kör" runs: the plan's first Step that may start (ready, or failed and tried again), as the server picks
 * it, and only when the server may run that Step itself. Undefined otherwise, also when the server runner is off.
 */
export function nextServerStep(plan: WorkAiPlan): WorkAiPlanStep | undefined {
  if (plan.server_runner !== "available" || plan.state !== "approved") return;
  const next = plan.steps.find(
    (entry) => entry.ai_status === "ready" || entry.ai_status === "failed",
  );
  return next?.server_startable ? next : undefined;
}

/**
 * Running an approved plan's next Step on the server (run_ai_plan) and stopping a run (cancel_ai_step_run). Both are
 * the owner's clicks and app-only tools. A run answers with the plan, which `take` shows; a refusal stands under the
 * Step it would have run. A stop, or a conflict that means the plan moved on, reads the plan again with `refresh`.
 */
export function useAiServerRun(
  transport: WorkTransport,
  plan: WorkAiPlan | undefined,
  take: (plan: WorkAiPlan) => void,
  refresh: () => void,
) {
  const offers = useToolSupport(transport);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<{
    stepId: string;
    kind: RunRefusal;
  }>();
  const [cancelling, setCancelling] = useState<{
    runId: string;
    state: "busy" | "failed";
  }>();
  const mounted = useMounted();
  const flight = useSingleFlight();
  const pendingRun = useRef<PendingKey | undefined>(undefined);
  const pendingCancel = useRef<PendingKey | undefined>(undefined);
  const next = plan ? nextServerStep(plan) : undefined;
  const active = plan?.steps.some((entry) => serverRunActive(entry.latest_run));

  function run() {
    if (!plan || !next || !flight.enter()) return;
    const stepId = next.step.id;
    const claimed = keyFor(
      pendingRun.current,
      JSON.stringify([plan.task_id, plan.digest, stepId]),
    );
    pendingRun.current = claimed;
    setBusy(true);
    setRefusal(undefined);
    transport
      .runAiPlan(plan.task_id, plan.digest, claimed.key)
      .then(
        (result) => {
          pendingRun.current = undefined;
          if (mounted.current) take(result.plan);
        },
        (error: unknown) => {
          if (!mounted.current) return;
          const failure = writeFailure(error);
          const reason = errorReason(error);
          if (reason && REASONS.has(reason)) {
            pendingRun.current = undefined;
            setRefusal({ stepId, kind: reason as RunRefusal });
            // The setting or the attempts may have moved: the plan says so once it is read again.
            refresh();
          } else if (failure === "conflict" || failure === "not_found") {
            pendingRun.current = undefined;
            refresh();
          } else setRefusal({ stepId, kind: failure });
        },
      )
      .finally(() => {
        flight.leave();
        if (mounted.current) setBusy(false);
      });
  }

  function cancel(target: Run) {
    if (!flight.enter()) return;
    const claimed = keyFor(
      pendingCancel.current,
      JSON.stringify([target.id, target.version]),
    );
    pendingCancel.current = claimed;
    setCancelling({ runId: target.id, state: "busy" });
    transport
      .cancelAiStepRun(target.id, target.version, claimed.key)
      .then(
        () => {
          pendingCancel.current = undefined;
          if (!mounted.current) return;
          setCancelling(undefined);
          refresh();
        },
        (error: unknown) => {
          if (!mounted.current) return;
          const failure = writeFailure(error);
          // The run moved on (it finished or was already stopped): what it is now is read again.
          if (failure === "conflict" || failure === "not_found") {
            pendingCancel.current = undefined;
            setCancelling(undefined);
            refresh();
          } else setCancelling({ runId: target.id, state: "failed" });
        },
      )
      .finally(() => flight.leave());
  }

  return {
    /** The Step "Kör" would run, with the button drawn: no refusal stands for it and no run is under way. */
    next:
      next &&
      !active &&
      refusal?.stepId !== next.step.id &&
      offers("run_ai_plan")
        ? next
        : undefined,
    /** True where the server runs the plan's Steps itself; otherwise Claude takes each next Step when asked. */
    runnerOn: plan?.server_runner === "available",
    busy,
    run,
    refusal,
    cancelOffered: offers("cancel_ai_step_run"),
    cancelling,
    cancel,
  };
}
export type AiServerRun = ReturnType<typeof useAiServerRun>;
