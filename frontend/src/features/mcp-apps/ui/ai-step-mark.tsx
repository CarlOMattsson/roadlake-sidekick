import type { ToolResults } from "@/lib/mcp/tool-results.generated";
import { aiStepLabelsFor } from "./ai-step-labels";
import "./ai-step-mark.css";

type ListedStep = ToolResults["list_task_steps"]["items"][number];

/** Who does a Step, as `list_task_steps` reports it. */
export type StepPerformer = ListedStep["performer"];
/** Where an AI Step stands; null for an owner Step. An older server leaves it out. */
export type AiStepState = ListedStep["ai_status"];

/** The states in which an AI Step waits for the owner: a result to review or a question to answer. */
export function waitsForOwner(state: AiStepState | undefined): boolean {
  return state === "to_review" || state === "needs_input";
}

/**
 * The mark of who does a Step: "Du" or "AI", and for an AI Step where it stands ("AI · att granska"). While the Step's
 * plan waits for the owner's approval, a Step that would read "redo" or "väntar" says "väntar på godkännande" instead.
 * It only reads; the owner reviews and answers through Claude. A Step from an older server has no performer and no mark.
 */
export function AiStepMark({
  performer,
  state,
  awaitingApproval = false,
  locale,
}: {
  performer: StepPerformer | undefined;
  state?: AiStepState;
  /** True while the Step's plan has not been approved. */
  awaitingApproval?: boolean;
  locale: string;
}) {
  if (!performer) return null;
  const t = aiStepLabelsFor(locale);
  const who = t.performer[performer];
  const held = awaitingApproval && (state === "ready" || state === "waiting");
  const where =
    performer === "ai" && state && state !== "done"
      ? t.status[held ? "awaiting_approval" : state]
      : undefined;
  return (
    <span
      className="sk-ai-mark"
      data-performer={performer}
      data-attention={waitsForOwner(state) ? "true" : undefined}
      role="img"
      aria-label={t.reading(t.performedBy[performer], where)}
    >
      <span aria-hidden="true">{where ? `${who} · ${where}` : who}</span>
    </span>
  );
}
