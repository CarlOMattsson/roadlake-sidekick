import { useCallback, useMemo } from "react";

import type { RoomTarget } from "../../mcp-apps/room-types";
import { DecisionCard } from "../../mcp-apps/ui/decision-card";
import { QuoteBlock } from "../../mcp-apps/ui/quote-block";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { ErrorNotice, SkeletonRows } from "../../mcp-apps/ui/states";
import { useRead } from "../../mcp-apps/ui/use-read";
import type { SuggestionLabels } from "./labels";
import {
  addedLine,
  appliedTarget,
  latestReasons,
  momentDay,
  payloadChanges,
  sourceQuotes,
  suggestionTitle,
  suggestionTrust,
  suggestionValue,
  type SuggestionDetail,
} from "./model";
import type { SuggestionTransport } from "./transport";
import { useDecisions } from "./use-decisions";
import "./suggestions.css";

/**
 * One suggestion in full (the Start room's `suggestion` view; the detail beside the inbox in a wide frame): what
 * approving would set, field by field, the proposer's "Varför", the check in words ("Kontrollerad · säker 94 %",
 * "Inte kontrollerad", or the trust note), the untrusted text it rests on in quotes that say where it comes from, who
 * proposed it and until when, and why it is not among the safe ones. Approve is the primary here; a suspicious card
 * has Avböj as the primary and "Godkänn ändå", which asks once. A card that is no longer waiting shows what became
 * of it, with the way to its record.
 */
export function SuggestionDetailView({
  api,
  t,
  id,
  initial,
  refreshKey,
  onOpenRecord,
}: {
  api: SuggestionTransport;
  t: SuggestionLabels;
  id: string;
  initial?: SuggestionDetail;
  refreshKey?: number;
  onOpenRecord?: (target: RoomTarget) => void;
}) {
  const read = useCallback(
    () => api.get(id).then((result) => result.suggestion),
    [api, id],
  );
  const [state, retry, replace] = useRead(read, refreshKey, initial);
  const receipt = useReceipt(id);
  const reread = useCallback(() => {
    read().then(replace, () => undefined);
  }, [read, replace]);
  const decisions = useDecisions({
    api,
    t,
    receipt,
    onSettled: reread,
    onOpen: onOpenRecord,
  });

  if (state.phase === "reading")
    return (
      <div className="start-detail-wait" aria-busy="true">
        <SkeletonRows rows={2} heading glyph={false} />
      </div>
    );
  if (state.phase === "failed")
    return (
      <ErrorNotice
        locale={t.dateLocale}
        subject="start:suggestion"
        cause={state.cause}
        onRetry={retry}
      />
    );
  return (
    <>
      <DetailCard
        detail={state.value}
        t={t}
        decision={decisions.card(state.value.id)}
        onAnswer={(answer, confirmed) =>
          decisions.answer(state.value, answer, confirmed)
        }
        onOpenRecord={onOpenRecord}
      />
      <ReceiptBar receipt={receipt} />
    </>
  );
}

function DetailCard({
  detail,
  t,
  decision,
  onAnswer,
  onOpenRecord,
}: {
  detail: SuggestionDetail;
  t: SuggestionLabels;
  decision: ReturnType<ReturnType<typeof useDecisions>["card"]>;
  onAnswer: (answer: "approve" | "dismiss", confirmed: boolean) => void;
  onOpenRecord?: (target: RoomTarget) => void;
}) {
  const locale = t.dateLocale;
  const trust = useMemo(
    () => suggestionTrust(detail, locale, latestReasons(detail)),
    [detail, locale],
  );
  const flagged = trust.state === "unsure" || trust.state === "suspicious";
  const title = suggestionTitle(detail.effect, detail.summary, t);
  const quotes = sourceQuotes(detail, t);
  const blockers = detail.blockers
    .map((code) => t.blockers[code])
    .filter((words): words is string => words !== undefined);

  // What became of a card that no longer waits (decided here, or elsewhere before this read).
  const target =
    decision.decided?.target ??
    appliedTarget(
      detail.applied,
      suggestionValue(detail.effect, detail.summary),
    );
  const settled =
    decision.decided ??
    (detail.state === "pending"
      ? undefined
      : {
          message:
            detail.state === "applied"
              ? addedLine(detail.effect, detail.summary, t)
              : (t.states[detail.state] ?? detail.state),
          hold: false,
        });

  return (
    <DecisionCard
      locale={locale}
      density="full"
      frame={false}
      headingLevel={2}
      kicker={t.kicker}
      title={title}
      changes={payloadChanges(detail, t)}
      why={detail.rationale || undefined}
      source={{ name: detail.automation_title }}
      trust={trust}
      edited={detail.edited}
      actions={{
        approve: () => onAnswer("approve", flagged),
        dismiss: () => onAnswer("dismiss", false),
      }}
      busy={decision.busy}
      failed={decision.failed}
      applyError={decision.applyError ?? detail.apply_error ?? undefined}
      decided={
        settled
          ? {
              message: settled.message,
              hold: settled.hold,
              open:
                target && onOpenRecord && detail.state !== "undone"
                  ? { label: t.open, onOpen: () => onOpenRecord(target) }
                  : undefined,
            }
          : undefined
      }
    >
      {quotes.map((quote, index) => (
        <QuoteBlock key={index} label={quote.label} text={quote.text} />
      ))}
      <p className="sk-card__meta start-detail-meta">
        {t.proposedBy(
          detail.automation_title,
          momentDay(detail.expires_at, locale),
        )}
      </p>
      {blockers.length > 0 && detail.state === "pending" ? (
        <p className="sk-card__meta start-detail-meta">
          {t.notInGroup} {blockers.join(", ")}.
        </p>
      ) : null}
    </DecisionCard>
  );
}
