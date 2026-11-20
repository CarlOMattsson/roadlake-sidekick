import { ReceiptBar, useReceipt } from "@/features/mcp-apps/ui/receipt";
import {
  StepActions as StepActionsView,
  type StepActionsProps,
} from "@/features/work-app/steps/step-actions";
import { TaskSteps as TaskStepsView } from "@/features/work-app/tasks/task-steps";
import type { ComponentProps } from "react";

/**
 * The Task view's Steps and a Step's Actions confirm a tick in the view's one receipt bar, which the Task view owns. These
 * wrappers stand in for that view in a test: the same component with the bar beside it (`.sk-receipt-slot`).
 */
export function TaskSteps(
  props: Omit<ComponentProps<typeof TaskStepsView>, "receipt">,
) {
  const receipt = useReceipt();
  return (
    <>
      <TaskStepsView {...props} receipt={receipt} />
      <ReceiptBar receipt={receipt} />
    </>
  );
}

export function StepActions(props: Omit<StepActionsProps, "receipt">) {
  const receipt = useReceipt();
  return (
    <>
      <StepActionsView {...props} receipt={receipt} />
      <ReceiptBar receipt={receipt} />
    </>
  );
}
