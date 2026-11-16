import { useState } from "react";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import type {
  WorkAiPlanStep,
  WorkAiReview,
  WorkTransport,
} from "../transport/transport";
import type { AiLabels } from "./ai-labels";
import { AiRunReview } from "./ai-run-review";
import "./ai.css";

/**
 * Under an AI Step whose latest run has something to look at (a result, a question or a failure): one meta line with
 * ⌄ that opens the run in place, the way a Step's Actions open from their count. Nothing for a Step without such a run.
 */
export function AiStepRun({
  entry,
  transport,
  labels: a,
  locale,
  onReviewed,
}: {
  entry: WorkAiPlanStep;
  transport: WorkTransport;
  labels: AiLabels;
  locale: string;
  onReviewed: (decision: WorkAiReview) => void;
}) {
  const [open, setOpen] = useState(false);
  const run = entry.latest_run;
  if (!run || !(run.has_result || run.has_question || run.state === "failed"))
    return null;
  const text =
    run.state === "to_review"
      ? a.openRun.review
      : run.state === "needs_input"
        ? a.openRun.question
        : a.openRun.look;
  return (
    <>
      <button
        type="button"
        className="work-step-actions-open work-ai-run-open"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {text}
        <ChevronDownIcon size={16} />
      </button>
      {open && (
        <AiRunReview
          // A new run (another attempt) is a new review: its text field and verdict start over.
          key={run.id}
          runId={run.id}
          title={entry.step.title}
          transport={transport}
          labels={a}
          locale={locale}
          onReviewed={onReviewed}
        />
      )}
    </>
  );
}
