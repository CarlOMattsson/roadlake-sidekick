import { useContext, useState } from "react";
import { aiUsageShown } from "../../mcp-apps/ai-usage-shown";
import { AiStepMark } from "../../mcp-apps/ui/ai-step-mark";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { RoomMessageContext } from "../../mcp-apps/ui/room-context";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { usd } from "../../mcp-apps/ui/usd";
import type { WorkAiPlan, WorkAiPlanStep } from "../transport/transport";
import {
  aiLabelsFor,
  approvedWhen,
  needsApproval,
  type AiLabels,
} from "./ai-labels";
import type { AiPlanState } from "./use-ai-plan";
import "./ai.css";

/**
 * The Task's AI plan, under its description. Without a plan: "Ingen plan än." and "Be Claude planera" (a message to
 * Claude; the button is not drawn on a phone). With a plan that waits for the owner (a draft, or a plan changed since
 * its approval): every Step with Du or AI, each AI Step folded to what it will do, the budget, "Godkänn plan" (the
 * digest the view read) and "Ändra" (a message to Claude). An approved plan is one line, "Godkänd 14:02", with its Steps
 * folded; each AI Step's state stands on the Step itself in the list below. Where the server runs Steps, an approved
 * plan whose next Step it may run has "Kör nästa steg" ("Kör igen" after a failure). What AI costs never stands open:
 * the Task's cost so far follows the budget among the folded Steps once it is above zero, and the month's sum only where
 * the instance shows AI cost. With the server runner off nothing of this is drawn.
 */
export function AiPlanCard({
  ai,
  title,
  locale,
  approveOffered,
}: {
  ai: AiPlanState;
  title: string;
  locale: string;
  approveOffered: boolean;
}) {
  const a = aiLabelsFor(locale);
  const send = useContext(RoomMessageContext);
  const [stepsOpen, setStepsOpen] = useState(false);
  const { plan, phase, approval, server } = ai;
  return (
    <section className="work-ai-plan">
      <h3>{a.heading}</h3>
      {phase === "loading" && (
        <p role="status" className="work-ai-meta">
          {a.loading}
        </p>
      )}
      {phase === "error" && (
        <ErrorNotice
          placement="row"
          locale={locale}
          cause={ai.readError}
          onRetry={ai.retry}
        />
      )}
      {phase === "ready" && plan?.state === "none" && (
        <div className="work-ai-actions">
          <p className="work-ai-meta">{a.none}</p>
          {send && (
            <button
              type="button"
              className="sk-btn--secondary sk-btn--compact work-ai-ask"
              onClick={() => void send(a.askPlanMessage(title, plan.task_id))}
            >
              {a.askPlan}
            </button>
          )}
        </div>
      )}
      {phase === "ready" && plan && plan.state !== "none" && (
        <>
          <PlanState plan={plan} labels={a} locale={locale} />
          {(needsApproval(plan) || stepsOpen) && (
            <>
              <ol className="work-ai-steps">
                {plan.steps.map((entry) => (
                  <PlanStep
                    key={entry.step.id}
                    entry={entry}
                    labels={a}
                    locale={locale}
                  />
                ))}
              </ol>
              <p className="work-ai-meta">{budgetLine(plan, a, locale)}</p>
              {plan.server_runner === "available" && aiUsageShown() && (
                <p className="work-ai-meta">
                  {a.month(
                    usd(plan.month_spent_usd, locale),
                    usd(plan.month_cap_usd, locale),
                  )}
                </p>
              )}
            </>
          )}
          <ApprovalNotice ai={ai} labels={a} locale={locale} />
          {ai.finished && (
            <p role="status" className="work-visually-hidden">
              {a.runFinished(ai.finished)}
            </p>
          )}
          <div className="work-ai-actions">
            {server.next && (
              <button
                type="button"
                className="sk-btn--secondary sk-btn--compact"
                disabled={server.busy}
                onClick={server.run}
              >
                {server.next.ai_status === "failed" ? a.runAgain : a.run}
              </button>
            )}
            {needsApproval(plan) && approveOffered && (
              <button
                type="button"
                className="sk-btn--secondary sk-btn--compact"
                disabled={approval === "busy"}
                onClick={ai.approve}
              >
                {a.approve}
              </button>
            )}
            {!needsApproval(plan) && (
              <button
                type="button"
                className="sk-btn--quiet sk-btn--compact work-ai-fold"
                aria-expanded={stepsOpen}
                onClick={() => setStepsOpen((open) => !open)}
              >
                {stepsOpen ? a.hideSteps : a.showSteps(plan.steps.length)}
                <ChevronDownIcon size={16} />
              </button>
            )}
            {send && (
              <button
                type="button"
                className="sk-btn--quiet sk-btn--compact"
                onClick={() => void send(a.changeMessage(title, plan.task_id))}
              >
                {a.change}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}

/** The plan's state under the heading: waiting for approval, approved at, or changed since the approval. */
function PlanState({
  plan,
  labels: a,
  locale,
}: {
  plan: WorkAiPlan;
  labels: AiLabels;
  locale: string;
}) {
  if (plan.state === "changed_since_approval")
    return <p className="work-ai-state work-ai-state--changed">{a.changed}</p>;
  if (plan.state === "approved" && plan.approved_at)
    return (
      <p className="work-ai-meta">
        {a.approvedAt(approvedWhen(plan.approved_at, locale))}
      </p>
    );
  return <p className="work-ai-meta">{a.draft}</p>;
}

/** What the last approval click did: read aloud when it passed, a line (with Reload or Try again) when it did not. */
function ApprovalNotice({
  ai,
  labels: a,
  locale,
}: {
  ai: AiPlanState;
  labels: AiLabels;
  locale: string;
}) {
  const { approval } = ai;
  if (approval === "approved") {
    // Where the server runs AI Steps its "Kör nästa steg" is what comes next; elsewhere Claude takes the next step, and
    // the line says so instead of leaving the owner waiting.
    const claudeNext = !ai.server.runnerOn;
    return (
      <p
        role="status"
        className={claudeNext ? "work-ai-meta" : "work-visually-hidden"}
      >
        {claudeNext ? a.approvedNext : a.approvedNow}
      </p>
    );
  }
  if (approval === "conflict")
    return (
      <div role="alert" className="work-banner">
        <p>{a.approveConflict}</p>
        <button type="button" onClick={ai.reloadAfterConflict}>
          {a.reload}
        </button>
      </div>
    );
  if (approval === "forbidden") return <p role="alert">{a.approveForbidden}</p>;
  if (approval === "idle" || approval === "busy") return null;
  return (
    <ErrorNotice
      placement="row"
      locale={locale}
      message={a.approveFailed}
      onRetry={approval === "failed" ? ai.approve : undefined}
    />
  );
}

/** One Step of the plan: Du or AI and its title; an AI Step opens to what it will do. */
function PlanStep({
  entry,
  labels: a,
  locale,
}: {
  entry: WorkAiPlanStep;
  labels: AiLabels;
  locale: string;
}) {
  const [open, setOpen] = useState(false);
  const { step, ai_spec: spec } = entry;
  const mark = <AiStepMark performer={step.performer} locale={locale} />;
  if (step.performer !== "ai" || !spec)
    return (
      <li className="work-ai-step">
        <span className="work-ai-step-line">
          {mark}
          <span className="work-ai-step-title">{step.title}</span>
        </span>
      </li>
    );
  const chars = spec.output.max_chars.toLocaleString(locale);
  return (
    <li className="work-ai-step">
      <button
        type="button"
        className="work-ai-step-line"
        aria-expanded={open}
        aria-label={a.detailsFor(step.title)}
        onClick={() => setOpen((value) => !value)}
      >
        {mark}
        <span className="work-ai-step-title">{step.title}</span>
        <ChevronDownIcon size={16} />
      </button>
      {open && (
        <div className="work-ai-spec">
          <p>{spec.goal}</p>
          {spec.done_when.length > 0 && <p>{a.doneWhen(spec.done_when)}</p>}
          <p>{a.tools(spec.capabilities.map((name) => a.capability[name]))}</p>
          <p>{a.output(spec.output.format, chars)}</p>
          {spec.stop_and_ask.length > 0 && <p>{a.asks(spec.stop_and_ask)}</p>}
          <p>{a.stepBudget(usd(spec.budget.max_usd, locale))}</p>
        </div>
      )}
    </li>
  );
}

/**
 * "Beräknad kostnad för AI-stegen: högst 1,50 USD (uppgiftens tak: 2,00 USD)." The AI Steps' budgets per attempt, added up. Where the
 * server runs Steps and they have cost something, what they cost so far follows, folded with the Steps.
 */
function budgetLine(plan: WorkAiPlan, a: AiLabels, locale: string): string {
  const steps = plan.steps.reduce(
    (sum, entry) => sum + (entry.ai_spec?.budget.max_usd ?? 0),
    0,
  );
  const budget = a.budget(usd(steps, locale), usd(plan.task_cap_usd, locale));
  return plan.server_runner === "available" && plan.task_spent_usd > 0
    ? `${budget} ${a.spent(usd(plan.task_spent_usd, locale))}`
    : budget;
}
