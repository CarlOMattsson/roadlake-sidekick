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
import { serverRunActive, useAiServerRun } from "./use-ai-server-run";

export type AiPlanPhase = "loading" | "ready" | "error";
/** The approval click: what it last did. A failure keeps its closed reason; `conflict` means the digest was stale. */
export type AiApproval = "idle" | "busy" | "approved" | WriteFailure;

/**
 * A Task's plan for AI steps, read while the Task is marked as possible with AI and the host answers get_ai_plan. The
 * plan is read again when the Task's version moves (an edit can change what the owner approves), when a run is
 * reviewed, and on Try again; a re-read keeps the plan on screen until the answer comes. `approve` sends exactly the
 * digest the view shows; a retry of the same click keeps its key. While the server holds a run (queued or running) the
 * plan is read again in the background, so its result turns up to review without a new message to Claude; the reads
 * stop when no run is under way or the view closes.
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
  // The plan on screen, so a newer answer can be compared with it before it replaces it.
  const shownPlan = useRef<WorkAiPlan | undefined>(undefined);
  // The title of a watched run's Step once that run has something for the owner: read aloud.
  const [finished, setFinished] = useState<string>();
  // Bumped when a watched read settles, so the next one is scheduled; and when the watch began.
  const [beats, setBeats] = useState(0);
  const watchedSince = useRef<number | undefined>(undefined);

  /**
   * Shows a plan that came from a run, a stop or a watched read. When an AI Step's state moved, the Step list is read
   * again so its marks follow; when a watched run ended with something to look at, that is read aloud.
   */
  const take = useCallback((next: WorkAiPlan) => {
    const before = shownPlan.current;
    shownPlan.current = next;
    setPlan(next);
    if (!before) return;
    if (statusesOf(before) !== statusesOf(next)) setStepsKey((n) => n + 1);
    const ended = next.steps.find(
      (entry) =>
        entry.latest_run &&
        ["to_review", "needs_input", "failed"].includes(
          entry.latest_run.state,
        ) &&
        serverRunActive(
          before.steps.find((old) => old.step.id === entry.step.id)?.latest_run,
        ),
    );
    if (ended) setFinished(ended.step.title);
  }, []);

  /** A read in the background (a watched run, or after a stop): a failure keeps the plan on screen. */
  const refresh = useCallback(() => {
    if (!taskId) return;
    const taken = ++ticket.current;
    transport
      .getAiPlan(taskId)
      .then(
        (result) => {
          if (taken === ticket.current && mounted.current) take(result.plan);
        },
        () => undefined,
      )
      .finally(() => {
        if (mounted.current) setBeats((n) => n + 1);
      });
  }, [taskId, transport, take, mounted]);

  const watching =
    shown &&
    phase === "ready" &&
    Boolean(plan?.steps.some((entry) => serverRunActive(entry.latest_run)));
  useEffect(() => {
    if (!watching) {
      watchedSince.current = undefined;
      return;
    }
    watchedSince.current ??= Date.now();
    // Often while a run is young, then calmly: a run takes seconds to minutes.
    const delay =
      Date.now() - watchedSince.current < WATCH_FAST_FOR_MS
        ? WATCH_FAST_MS
        : WATCH_SLOW_MS;
    const timer = setTimeout(refresh, delay);
    return () => clearTimeout(timer);
  }, [watching, beats, refresh]);

  useEffect(() => {
    if (!shown || !taskId) return;
    const taken = ++ticket.current;
    transport.getAiPlan(taskId).then(
      (result) => {
        if (taken !== ticket.current || !mounted.current) return;
        shownPlan.current = result.plan;
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
          shownPlan.current = result.plan;
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

  const server = useAiServerRun(transport, plan, take, refresh);

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
    server,
    finished,
  };
}
export type AiPlanState = ReturnType<typeof useAiPlan>;

const WATCH_FAST_MS = 4_000;
const WATCH_SLOW_MS = 15_000;
const WATCH_FAST_FOR_MS = 60_000;

/** Where each AI Step stands, as one string: equal strings mean the Step marks have nothing new to show. */
function statusesOf(plan: WorkAiPlan): string {
  return plan.steps
    .map((entry) => `${entry.ai_status}:${entry.latest_run?.state}`)
    .join(",");
}
