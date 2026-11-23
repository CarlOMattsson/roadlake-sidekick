import { useState, type ReactNode } from "react";

import type { RoomTarget } from "../../mcp-apps/room-types";
import { ApproveGroup } from "../../mcp-apps/ui/approve-group";
import { CardFoot } from "../../mcp-apps/ui/card";
import { decisionLabelsFor } from "../../mcp-apps/ui/decision-labels";
import { AppFrame } from "../../mcp-apps/ui/layout";
import { OpenLink } from "../../mcp-apps/ui/open-link";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { ErrorNotice, SkeletonRows } from "../../mcp-apps/ui/states";
import type { SuggestionLabels } from "./labels";
import {
  inboxOf,
  MAX_PER_CONFIRMATION,
  suggestionTitle,
  type DecisionsResult,
  type SuggestionItem,
  type SuggestionPage,
} from "./model";
import { ReviewCard, useInbox } from "./inbox";
import type { SuggestionTransport } from "./transport";
import { useDecisions } from "./use-decisions";
import "./suggestions.css";

/**
 * The inbox as an inline card in the conversation (list_suggestions): the first safe group with its one button (at
 * most three per confirmation), or else the first card to review, and "Öppna Förslag · n till ›". Each answer works
 * in the card without a new turn of the model, with Ångra in the card's receipt bar. Never more than one group or one
 * card, so the card stays within a phone's card height.
 */
export function SuggestionsCard({
  api,
  t,
  initial,
  onOpenFull,
  onOpenRecord,
}: {
  api: SuggestionTransport;
  t: SuggestionLabels;
  initial?: SuggestionPage;
  /** Opens the full view: the inbox, or `target` (one suggestion) on it. */
  onOpenFull?: (target?: RoomTarget) => void;
  onOpenRecord?: (target: RoomTarget) => void;
}) {
  const inbox = useInbox(api, initial);
  const receipt = useReceipt();
  const decisions = useDecisions({
    api,
    t,
    receipt,
    onSettled: inbox.reload,
    onOpen: onOpenRecord,
  });
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  const { read } = inbox;

  if (read.phase !== "ready")
    return (
      <InlineFrame>
        <div className="sk-card start-card">
          <p className="sk-eyebrow">{t.title}</p>
          {read.phase === "reading" ? (
            <SkeletonRows rows={2} glyph={false} />
          ) : (
            <ErrorNotice
              locale={t.dateLocale}
              subject="start"
              cause={read.cause}
              onRetry={inbox.retry}
            />
          )}
        </div>
      </InlineFrame>
    );

  const { groups, review } = inboxOf(read.page);
  const group = groups[0];
  const waiting =
    groups.reduce((sum, entry) => sum + entry.items.length, 0) + review.length;
  const shown = group
    ? Math.min(group.items.length, MAX_PER_CONFIRMATION)
    : review.length > 0
      ? 1
      : 0;
  const rest = waiting - shown;
  const foot = onOpenFull ? (
    <CardFoot>
      <OpenLink
        label={t.openInbox}
        more={rest > 0 ? t.moreWaiting(rest) : undefined}
        onOpen={() => onOpenFull()}
      />
    </CardFoot>
  ) : null;

  if (group) {
    const state = decisions.group(group.group.group_digest);
    return (
      <InlineFrame>
        <div className="sk-card start-card">
          <p className="sk-eyebrow">
            {`${t.title} · ${decisionLabelsFor(t.dateLocale).from(group.group.automation_title)}`}
          </p>
          {state.decided ? (
            <p className="sk-card__title start-card-done">
              {state.note ?? state.decided}
            </p>
          ) : (
            <ApproveGroup
              locale={t.dateLocale}
              title={t.safeCount(group.items.length)}
              items={group.items.map((item) => ({
                id: item.id,
                label: suggestionTitle(item.effect, item.summary, t),
              }))}
              excluded={excluded}
              onToggle={(id) =>
                setExcluded((now) => {
                  const next = new Set(now);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  return next;
                })
              }
              onApproveAll={(ids) => decisions.approveGroup(group, ids)}
              busy={state.busy}
              failed={state.failed}
              max={MAX_PER_CONFIRMATION}
            />
          )}
          {foot}
        </div>
        <ReceiptBar receipt={receipt} />
      </InlineFrame>
    );
  }

  const first = review[0];
  if (first)
    return (
      <InlineFrame>
        <div className="start-card-single">
          <ReviewCard
            item={first}
            t={t}
            state={decisions.card(first.id)}
            onAnswer={(answer, confirmed) =>
              decisions.answer(first, answer, confirmed)
            }
            onOpen={
              onOpenFull
                ? () =>
                    onOpenFull({
                      room: "start",
                      view: "suggestion",
                      id: first.id,
                      label: t.kicker,
                    })
                : undefined
            }
            onOpenRecord={onOpenRecord}
          />
          {foot ? <div className="start-card-foot">{foot}</div> : null}
        </div>
        <ReceiptBar receipt={receipt} />
      </InlineFrame>
    );

  return (
    <InlineFrame>
      <div className="sk-card start-card">
        <p className="sk-eyebrow">{t.title}</p>
        <p className="sk-card__title">{t.empty}</p>
        {foot}
      </div>
    </InlineFrame>
  );
}

/**
 * The receipt card after Claude decided or undid suggestions in the chat (decide_suggestions, undo_suggestion):
 * what was decided in a line, how many were not taken, and the way to the inbox.
 */
export function DecidedCard({
  t,
  result,
  onOpenFull,
}: {
  t: SuggestionLabels;
  result: DecisionsResult | { undone: true };
  onOpenFull?: () => void;
}) {
  let title: string;
  let refused = 0;
  if ("undone" in result) title = t.undoneTitle;
  else {
    const taken = result.items.filter((item) => !item.error_code);
    refused = result.items.length - taken.length;
    title = t.decidedTitle(
      taken.filter((item) => item.state === "applied").length,
      taken.filter((item) => item.state === "dismissed").length,
    );
  }
  return (
    <InlineFrame>
      <div className="sk-card start-card">
        <p className="sk-eyebrow">{t.title}</p>
        <p className="sk-card__title">{title}</p>
        {refused > 0 ? (
          <p className="sk-card__meta">{t.refused(refused)}</p>
        ) : null}
        {onOpenFull ? (
          <CardFoot>
            <OpenLink label={t.openInbox} onOpen={onOpenFull} />
          </CardFoot>
        ) : null}
      </div>
    </InlineFrame>
  );
}

function InlineFrame({ children }: { children: ReactNode }) {
  return (
    <section className="sidekick-start start-inline">
      <AppFrame mode="inline">{children}</AppFrame>
    </section>
  );
}

/**
 * One suggestion inline (get_suggestion in the chat): the decision card with its answers, its title leading to the
 * suggestion in the full view, and Ångra in the card's receipt bar.
 */
export function SuggestionInlineCard({
  api,
  t,
  detail,
  onOpenFull,
  onOpenRecord,
}: {
  api: SuggestionTransport;
  t: SuggestionLabels;
  detail: SuggestionItem;
  onOpenFull?: (target?: RoomTarget) => void;
  onOpenRecord?: (target: RoomTarget) => void;
}) {
  const receipt = useReceipt(detail.id);
  const decisions = useDecisions({
    api,
    t,
    receipt,
    onSettled: () => undefined,
    onOpen: onOpenRecord,
  });
  return (
    <InlineFrame>
      <ReviewCard
        item={detail}
        t={t}
        state={decisions.card(detail.id)}
        onAnswer={(answer, confirmed) =>
          decisions.answer(detail, answer, confirmed)
        }
        onOpen={
          onOpenFull
            ? () =>
                onOpenFull({
                  room: "start",
                  view: "suggestion",
                  id: detail.id,
                  label: t.kicker,
                })
            : undefined
        }
        onOpenRecord={onOpenRecord}
      />
      <ReceiptBar receipt={receipt} />
    </InlineFrame>
  );
}
