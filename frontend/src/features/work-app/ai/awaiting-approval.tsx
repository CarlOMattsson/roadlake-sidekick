import { createContext, useContext, type ReactNode } from "react";
import type { WorkAiPlan } from "../transport/transport";
import { needsApproval } from "./ai-labels";

const AwaitingApprovalContext = createContext(false);

/**
 * Tells the Steps below that the Task's AI plan waits for the owner (a draft, or changed since its approval), so an
 * AI Step's mark says "väntar på godkännande" rather than "redo". Without a plan nothing is awaited.
 */
export function AwaitingApproval({
  plan,
  children,
}: {
  plan: WorkAiPlan | undefined;
  children: ReactNode;
}) {
  return (
    <AwaitingApprovalContext.Provider
      value={Boolean(plan && needsApproval(plan))}
    >
      {children}
    </AwaitingApprovalContext.Provider>
  );
}

/** True while the Task's AI plan waits for the owner's approval. */
export function useAwaitingApproval(): boolean {
  return useContext(AwaitingApprovalContext);
}
