import { aiLabelsFor } from "./ai-labels";
import "../../mcp-apps/ui/ai-step-mark.css";

/** How far a Task has come with AI, as its row shows it: marked as possible, or its AI plan approved. */
export type AiMarkState = "possible" | "approved";

/**
 * The mark a Task's row shows, from the fields a list sends: `approved` once its AI plan is approved, `possible` while
 * it is only marked, and none for a Task without either or one that is done or cancelled (nothing is left to do).
 */
export function aiMarkOf(item: {
  kind?: string;
  status?: string;
  ai_possible?: boolean;
  ai_plan_approved?: boolean;
}): AiMarkState | undefined {
  if (item.kind !== undefined && item.kind !== "task") return undefined;
  if (item.status === "completed" || item.status === "cancelled")
    return undefined;
  if (item.ai_plan_approved) return "approved";
  return item.ai_possible ? "possible" : undefined;
}

/** What the mark says to a screen reader: `possible` or `planApproved`. */
export function aiMarkLabel(state: AiMarkState, locale: string): string {
  const a = aiLabelsFor(locale);
  return state === "approved" ? a.planApproved : a.possible;
}

/**
 * The small "AI" on a Task's row, read aloud as `possible`. Once the AI plan is approved it says "AI ✓" in the text
 * colour, read aloud as `planApproved`: the check tells the two apart without relying on colour.
 */
export function AiTaskMark({
  locale,
  state = "possible",
}: {
  locale: string;
  state?: AiMarkState;
}) {
  const a = aiLabelsFor(locale);
  return (
    <span
      className="sk-ai-mark"
      data-approved={state === "approved" ? "true" : undefined}
      role="img"
      aria-label={aiMarkLabel(state, locale)}
    >
      <span aria-hidden="true">
        {state === "approved" ? `${a.mark} ✓` : a.mark}
      </span>
    </span>
  );
}
