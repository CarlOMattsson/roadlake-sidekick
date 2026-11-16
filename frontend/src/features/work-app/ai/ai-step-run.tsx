import { useState } from "react";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type {
  WorkAiPlanStep,
  WorkAiReview,
  WorkTransport,
} from "../transport/transport";
import type { AiLabels } from "./ai-labels";
import { AiRunReview } from "./ai-run-review";
import { serverRunActive, type AiServerRun } from "./use-ai-server-run";
import "./ai.css";

/**
 * Under an AI Step: what the server is doing with it, why it did not run it, and its latest run to look at. A run the
 * server holds is one line, "I kö på servern" or "Körs på servern", with "Avbryt"; a refusal of "Kör" is one calm line
 * (with Try again when it may pass); a run with a result, a question or a failure is a meta line with ⌄ that opens it in
 * place, the way a Step's Actions open from their count. Nothing for a Step with none of these.
 */
export function AiStepRun({
  entry,
  transport,
  server,
  labels: a,
  locale,
  onReviewed,
}: {
  entry: WorkAiPlanStep;
  transport: WorkTransport;
  server: AiServerRun;
  labels: AiLabels;
  locale: string;
  onReviewed: (decision: WorkAiReview) => void;
}) {
  const run = entry.latest_run;
  const refusal =
    server.refusal?.stepId === entry.step.id ? server.refusal.kind : undefined;
  return (
    <>
      {serverRunActive(run) && (
        <ServerRunLine
          title={entry.step.title}
          state={run.state === "queued" ? "queued" : "running"}
          cancelling={
            server.cancelling?.runId === run.id
              ? server.cancelling.state
              : undefined
          }
          onCancel={server.cancelOffered ? () => server.cancel(run) : undefined}
          labels={a}
          locale={locale}
        />
      )}
      {refusal === "failed" ? (
        <ErrorNotice
          placement="row"
          locale={locale}
          message={a.runRefused.failed}
          onRetry={server.run}
        />
      ) : (
        refusal && (
          <p role="status" className="work-ai-run-note">
            {a.runRefused[refusal]}
          </p>
        )
      )}
      {run &&
        (run.has_result || run.has_question || run.state === "failed") && (
          <RunOpener
            run={run}
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

/** "I kö på servern · Avbryt": a run the server holds, and the stop when the host offers it. */
function ServerRunLine({
  title,
  state,
  cancelling,
  onCancel,
  labels: a,
  locale,
}: {
  title: string;
  state: "queued" | "running";
  cancelling: "busy" | "failed" | undefined;
  onCancel: (() => void) | undefined;
  labels: AiLabels;
  locale: string;
}) {
  return (
    <>
      <div className="work-ai-run-line">
        <p role="status">{a.runState[state]}</p>
        {onCancel && (
          <button
            type="button"
            className="sk-btn--quiet sk-btn--compact"
            aria-label={a.cancelRunFor(title)}
            disabled={cancelling === "busy"}
            onClick={onCancel}
          >
            {a.cancel}
          </button>
        )}
      </div>
      {cancelling === "failed" && (
        <ErrorNotice
          placement="row"
          locale={locale}
          message={a.cancelFailed}
          onRetry={onCancel}
        />
      )}
    </>
  );
}

/** The meta line with ⌄ that opens the latest run for review, an answer or a look. */
function RunOpener({
  run,
  title,
  transport,
  labels: a,
  locale,
  onReviewed,
}: {
  run: NonNullable<WorkAiPlanStep["latest_run"]>;
  title: string;
  transport: WorkTransport;
  labels: AiLabels;
  locale: string;
  onReviewed: (decision: WorkAiReview) => void;
}) {
  const [open, setOpen] = useState(false);
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
          title={title}
          transport={transport}
          labels={a}
          locale={locale}
          onReviewed={onReviewed}
        />
      )}
    </>
  );
}
