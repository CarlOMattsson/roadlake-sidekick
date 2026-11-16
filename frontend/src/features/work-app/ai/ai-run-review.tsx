import { useEffect, useId, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import { useSingleFlight } from "../shared/use-single-flight";
import { useCutText } from "../tasks/use-cut-text";
import {
  writeFailure,
  type WorkAiReview,
  type WorkAiRun,
  type WorkTransport,
  type WriteFailure,
} from "../transport/transport";
import { usd, type AiLabels } from "./ai-labels";

type Run = WorkAiRun["run"];
/** The verdicts each state of a run takes (the server refuses the rest). */
const DECISIONS: Partial<Record<Run["state"], readonly WorkAiReview[]>> = {
  to_review: ["accept", "redo", "reject"],
  needs_input: ["answer", "reject"],
  failed: ["reject"],
};
type Sent = { decision: WorkAiReview } | { failure: WriteFailure };

/**
 * One run of an AI Step, opened from the Step's AI line: the model and cost, the question or the result as plain text
 * (React text, so no markup, link or image in it is ever drawn or fetched), the checklist the run reported, and the
 * owner's verdict. Redo and Answer open a text field first; Accept and Reject write at once. A verdict is written at the
 * run's version; a retry of the same verdict keeps its key.
 */
export function AiRunReview({
  runId,
  title,
  transport,
  labels: a,
  locale,
  onReviewed,
}: {
  runId: string;
  title: string;
  transport: WorkTransport;
  labels: AiLabels;
  locale: string;
  onReviewed: (decision: WorkAiReview) => void;
}) {
  const [read, setRead] = useState<{
    phase: "loading" | "ready" | "error";
    run?: WorkAiRun;
    error?: unknown;
  }>({ phase: "loading" });
  const [reads, setReads] = useState(0);
  // The verdict whose text field is open (Redo's comment, the answer to a question).
  const [writing, setWriting] = useState<"redo" | "answer">();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<Sent>();
  const [full, setFull] = useState(false);
  const resultText = read.run?.content?.result_text;
  const { ref: textRef, cut } = useCutText<HTMLParagraphElement>(resultText);
  const mounted = useMounted();
  const flight = useSingleFlight();
  const pending = useRef<PendingKey | undefined>(undefined);
  // The last verdict sent, for Try again after a failure that may pass.
  const last = useRef<{ decision: WorkAiReview; comment: string | null }>(
    undefined,
  );
  const fieldId = useId();

  useEffect(() => {
    let live = true;
    transport.getAiStepRun(runId).then(
      (run) => live && setRead({ phase: "ready", run }),
      (error: unknown) => live && setRead({ phase: "error", error }),
    );
    return () => {
      live = false;
    };
  }, [transport, runId, reads]);

  function review(run: Run, decision: WorkAiReview, comment: string | null) {
    if (!flight.enter()) return;
    const claimed = keyFor(
      pending.current,
      JSON.stringify([run.id, run.version, decision, comment]),
    );
    pending.current = claimed;
    last.current = { decision, comment };
    setBusy(true);
    setSent(undefined);
    transport
      .reviewAiStepResult(run.id, run.version, decision, comment, claimed.key)
      .then(
        (next) => {
          pending.current = undefined;
          if (!mounted.current) return;
          setRead((current) => ({
            ...current,
            run: { run: next.run, content: current.run?.content ?? null },
          }));
          setWriting(undefined);
          setText("");
          setSent({ decision });
          onReviewed(decision);
        },
        (error: unknown) => {
          if (mounted.current) setSent({ failure: writeFailure(error) });
        },
      )
      .finally(() => {
        flight.leave();
        if (mounted.current) setBusy(false);
      });
  }

  if (read.phase === "loading")
    return (
      <p role="status" className="work-ai-meta">
        {a.loadingRun}
      </p>
    );
  if (read.phase === "error" || !read.run)
    return (
      <ErrorNotice
        placement="row"
        locale={locale}
        cause={read.error}
        onRetry={() => {
          setRead({ phase: "loading" });
          setReads((n) => n + 1);
        }}
      />
    );
  const { run, content } = read.run;
  const decisions = DECISIONS[run.state] ?? [];
  const cost =
    run.cost_source === "none"
      ? undefined
      : run.cost_source === "provider"
        ? usd(run.cost_usd, locale)
        : `${usd(run.cost_usd, locale)} ${a.estimated}`;
  const meta = [run.model, cost, a.attempt(run.attempt)].filter(Boolean);
  const checklist = content?.checklist ?? [];
  const checked = checklist.filter((entry) => entry.done).length;
  const failed = sent && "failure" in sent ? sent.failure : undefined;
  return (
    <section className="work-ai-run" aria-label={a.resultFor(title)}>
      <p className="work-ai-meta">{meta.join(" · ")}</p>
      {run.state === "failed" && (
        <p className="work-ai-meta">{a.failed(run.failure_category)}</p>
      )}
      {content?.question && (
        <blockquote className="work-ai-question">
          <p className="work-ai-label">{a.question}</p>
          <p className="work-ai-text">{content.question}</p>
        </blockquote>
      )}
      {content?.result_summary && (
        <p className="work-ai-summary">{content.result_summary}</p>
      )}
      {content?.result_text && (
        <>
          <p
            ref={textRef}
            className={
              full ? "work-ai-text" : "work-ai-text work-ai-text--clamped"
            }
          >
            {content.result_text}
          </p>
          {/* Offered while the eight drawn lines cut the text (measured; before that, a guess from its size), and while
              it is open, so it can be closed again. */}
          {(full ||
            (cut ??
              (content.result_text.length > 280 ||
                content.result_text.split("\n").length > 8))) && (
            <button
              type="button"
              className="sk-btn--quiet sk-btn--compact work-more-link"
              onClick={() => setFull((value) => !value)}
            >
              {full ? a.showLess : a.showAll}
            </button>
          )}
        </>
      )}
      {checklist.length > 0 && (
        <p className="work-ai-meta">{a.checklist(checked, checklist.length)}</p>
      )}
      {content?.comment && (
        <p className="work-ai-meta">
          {a.yourComment} {content.comment}
        </p>
      )}
      {content?.answer && (
        <p className="work-ai-meta">
          {a.yourAnswer} {content.answer}
        </p>
      )}
      {writing && (
        <div className="work-ai-reply">
          <label htmlFor={fieldId}>
            {writing === "redo" ? a.redoComment : a.answerLabel}
          </label>
          <textarea
            id={fieldId}
            rows={3}
            maxLength={1000}
            value={text}
            disabled={busy}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
      )}
      {decisions.length > 0 && (
        <div className="work-ai-actions">
          {writing ? (
            <>
              <button
                type="button"
                className="sk-btn--secondary sk-btn--compact"
                disabled={busy || (writing === "answer" && !text.trim())}
                onClick={() =>
                  review(run, writing, text.trim() ? text.trim() : null)
                }
              >
                {writing === "redo" ? a.sendRedo : a.answer}
              </button>
              <button
                type="button"
                className="sk-btn--quiet sk-btn--compact"
                disabled={busy}
                onClick={() => {
                  setWriting(undefined);
                  setText("");
                }}
              >
                {a.cancel}
              </button>
            </>
          ) : (
            decisions.map((decision) => (
              <button
                key={decision}
                type="button"
                className={
                  decision === "accept" || decision === "answer"
                    ? "sk-btn--secondary sk-btn--compact"
                    : "sk-btn--quiet sk-btn--compact"
                }
                disabled={busy}
                onClick={() =>
                  decision === "redo" || decision === "answer"
                    ? setWriting(decision)
                    : review(run, decision, null)
                }
              >
                {a[decision]}
              </button>
            ))
          )}
        </div>
      )}
      {sent && "decision" in sent && (
        <p role="status" className="work-ai-meta">
          {a.reviewed[sent.decision]}
        </p>
      )}
      {failed === "conflict" ? (
        <div role="alert" className="work-banner">
          <p>{a.reviewConflict}</p>
          <button
            type="button"
            onClick={() => {
              pending.current = undefined;
              setSent(undefined);
              setRead({ phase: "loading" });
              setReads((n) => n + 1);
            }}
          >
            {a.reload}
          </button>
        </div>
      ) : (
        failed && (
          <ErrorNotice
            placement="row"
            locale={locale}
            message={a.reviewFailed}
            onRetry={
              failed === "failed"
                ? () =>
                    last.current &&
                    review(run, last.current.decision, last.current.comment)
                : undefined
            }
          />
        )
      )}
    </section>
  );
}
