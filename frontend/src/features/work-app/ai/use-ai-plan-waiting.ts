import { useEffect, useState } from "react";
import { useToolSupport } from "../../mcp-apps/tool-support";
import type { WorkTransport } from "../transport/transport";
import { needsApproval } from "./ai-labels";

/** A Task's AI plan that waits for the owner: how many of its Steps AI does. */
export type AiPlanWaiting = { aiSteps: number };

/**
 * Whether a Task's AI plan waits for the owner's approval, for the inline Task card, which reads no plan of its own.
 * One get_ai_plan per Task, and only while `enabled` (the Task is marked as possible with AI) and the host answers the
 * tool. A read that fails says nothing: the card is then the card it was without AI.
 */
export function useAiPlanWaiting(
  transport: WorkTransport,
  taskId: string,
  enabled: boolean,
): AiPlanWaiting | undefined {
  const offers = useToolSupport(transport);
  const wanted = enabled && offers("get_ai_plan");
  const [read, setRead] = useState<{
    taskId: string;
    waiting: AiPlanWaiting | undefined;
  }>();
  useEffect(() => {
    if (!wanted) return undefined;
    let live = true;
    transport.getAiPlan(taskId).then(
      ({ plan }) => {
        if (!live) return;
        setRead({
          taskId,
          waiting: needsApproval(plan)
            ? {
                aiSteps: plan.steps.filter(
                  (entry) => entry.step.performer === "ai",
                ).length,
              }
            : undefined,
        });
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [wanted, transport, taskId]);
  return wanted && read?.taskId === taskId ? read.waiting : undefined;
}
