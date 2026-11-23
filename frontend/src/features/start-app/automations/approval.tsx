import { useEffect, useId, useRef } from "react";

import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import type { AutomationLabels } from "./labels";
import {
  approvalNeed,
  capital,
  effectsWords,
  autoApplyLimits,
  momentText,
  type AutomationRecord,
} from "./model";
import type { AutomationTransport } from "./transport";
import { useApproval } from "./use-approval";

/**
 * The approval of one automation, last in its detail, under everything it approves. Its state comes from the server's
 * record (approvalNeed): approved (when, and that a change asks again), archived, not complete enough to approve, or
 * waiting for the owner.
 *
 * Waiting, it says what an approval binds and offers Godkänn. A spec that applies suggestions without a click offers
 * "Godkänn…" instead, which opens a separate step in the card: what will happen without the owner's click, in plain
 * words, a box the owner ticks, and Avbryt and Godkänn. Only Godkänn with the box ticked sends the approval, with the
 * confirmation; the box cannot be ticked by a second press on the same spot, so a double press never approves it.
 */
export function ApprovalCard({
  api,
  record,
  t,
  receipt,
  onApproved,
  onChanged,
}: {
  api: AutomationTransport;
  record: AutomationRecord;
  t: AutomationLabels;
  receipt: ReceiptState;
  onApproved: (record: AutomationRecord) => void;
  onChanged: () => void;
}) {
  const need = approvalNeed(record);
  const approval = useApproval({
    api,
    record,
    t,
    receipt,
    onApproved,
    onChanged,
  });
  const headingId = useId();
  const confirmId = useId();
  const startButton = useRef<HTMLButtonElement>(null);
  const confirmHeading = useRef<HTMLHeadingElement>(null);
  const checkbox = useRef<HTMLInputElement>(null);
  const { state } = approval;

  // The step opens with the focus on its heading, so a screen reader reads the consequences first; Avbryt returns it.
  const step = state.step;
  const wasConfirm = useRef(false);
  useEffect(() => {
    if (step === "confirm") confirmHeading.current?.focus();
    else if (wasConfirm.current) startButton.current?.focus();
    wasConfirm.current = step === "confirm";
  }, [step]);
  useEffect(() => {
    if (state.tickFirst) checkbox.current?.focus();
  }, [state.tickFirst]);

  if (need.kind === "approved")
    return (
      <section
        className="sk-card start-approval"
        aria-labelledby={headingId}
        data-approval="approved"
      >
        <p className="sk-eyebrow">{t.approveKicker}</p>
        <h3 className="sk-card__title" id={headingId}>
          {need.at
            ? t.approvedTitle(momentText(need.at, t.dateLocale, false))
            : t.states.on}
        </h3>
        {need.auto ? (
          <p className="start-approval-body">{t.approvedAuto}</p>
        ) : null}
        {need.paused ? (
          <p className="start-approval-body">{t.pausedNote}</p>
        ) : null}
        <p className="sk-card__meta">{t.approvedNote}</p>
      </section>
    );
  if (need.kind === "archived")
    return (
      <section className="sk-card start-approval" data-approval="archived">
        <p className="sk-card__meta">{t.archivedNote}</p>
      </section>
    );
  if (need.kind === "incomplete") {
    const why = need.missing.map((part) =>
      part === "sources" ? t.needsSources : t.needsEffects,
    );
    const sentence = why.join(` ${t.and} `);
    return (
      <section
        className="sk-card start-approval"
        aria-labelledby={headingId}
        data-approval="incomplete"
      >
        <h3 className="sk-card__title" id={headingId}>
          {t.cannotTitle}
        </h3>
        <p className="start-approval-body">
          {`${capital(sentence)}. ${t.askClaude}`}
        </p>
      </section>
    );
  }
  if (!api.approve) return null;

  const limits = autoApplyLimits(record);
  const autoWords = capital(effectsWords(record.auto_effects, t));
  const busyLabel = state.busy ? t.approving : undefined;
  return (
    <section
      className="sk-card start-approval"
      aria-labelledby={headingId}
      data-approval={state.step === "confirm" ? "confirm" : "waiting"}
    >
      <p className="sk-eyebrow">{t.approveKicker}</p>
      <h3 className="sk-card__title" id={headingId}>
        {t.approveTitle}
      </h3>
      <p className="start-approval-body">{t.approveBody}</p>
      {state.step === "start" ? (
        <div className="sk-card__actions start-approval-actions">
          <button
            ref={startButton}
            type="button"
            className="sk-btn sk-btn--primary"
            aria-busy={state.busy || undefined}
            aria-disabled={state.busy || undefined}
            onClick={approval.begin}
          >
            {busyLabel ?? (approval.auto ? t.approveStep : t.approve)}
          </button>
        </div>
      ) : (
        <div className="start-confirm" role="group" aria-labelledby={confirmId}>
          <h4
            ref={confirmHeading}
            className="start-confirm-title"
            id={confirmId}
            tabIndex={-1}
          >
            {t.confirmHeading}
          </h4>
          <ul className="start-confirm-lines">
            {(record.auto_effects.length > 0
              ? t.confirmLines(
                  autoWords,
                  record.auto_threshold,
                  limits.perRun,
                  limits.perDay,
                )
              : [t.confirmNoKinds]
            ).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <label className="start-confirm-check">
            <input
              ref={checkbox}
              type="checkbox"
              checked={state.confirmed}
              disabled={state.busy}
              onChange={(event) => approval.setConfirmed(event.target.checked)}
            />
            <span>{t.confirmCheck}</span>
          </label>
          <p className="sk-card__meta">{t.confirmRequired}</p>
          <div className="start-confirm-actions">
            <button
              type="button"
              className="sk-btn sk-btn--secondary"
              disabled={state.busy}
              onClick={approval.cancel}
            >
              {t.cancel}
            </button>
            <button
              type="button"
              className="sk-btn sk-btn--primary"
              aria-disabled={!state.confirmed || state.busy || undefined}
              aria-busy={state.busy || undefined}
              aria-describedby={
                state.tickFirst ? `${confirmId}-tick` : undefined
              }
              onClick={approval.confirm}
            >
              {busyLabel ?? t.approve}
            </button>
          </div>
          {state.tickFirst ? (
            <p
              className="start-confirm-tick"
              id={`${confirmId}-tick`}
              role="status"
            >
              {t.tickFirst}
            </p>
          ) : null}
        </div>
      )}
      {state.failed ? (
        <p className="start-approval-error" role="alert">
          {t.approveFailed}
        </p>
      ) : null}
    </section>
  );
}
