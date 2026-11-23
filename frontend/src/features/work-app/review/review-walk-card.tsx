import { useEffect, useRef, type ReactNode, type Ref } from "react";
import { Card } from "../../mcp-apps/ui/card";
import { buttonClass } from "../../mcp-apps/ui/button";
import { Progress } from "../../mcp-apps/ui/progress";
import { ReceiptBar } from "../../mcp-apps/ui/receipt";
import { EmptyState, ErrorNotice } from "../../mcp-apps/ui/states";
import { NoticeRow } from "../inline/inline-summary-list";
import {
  reviewReason,
  type ReviewChoice,
  type ReviewQueuePage,
  type ReviewQueueTask,
} from "./review-walk-data";
import type { ReviewWalkLabels } from "./review-walk-labels";
import type { ReviewTransport } from "./review-walk-transport";
import { useReviewWalk, type ReviewWalk } from "./use-review-walk";
import "./review-walk.css";

/**
 * The review card: the queue get_review_queue answered, walked through one Task at a time in the card, so going
 * through a long list takes a tap per Task and no turn of the model. The head says where the walk stands (such as
 * "12 of 120") and offers a skip; under it the Task, why it is in the queue, and the four quick decisions (done, keep,
 * move, remove). Move turns the row into its two days in place. Every decision is saved at once, one Task per call,
 * and confirmed in the receipt bar with an undo.
 */
export function ReviewWalkCard({
  initial,
  transport,
  labels,
  onModelContext,
  cause,
}: {
  /** The page the tool result carried; without one the card reads the queue itself. */
  initial?: ReviewQueuePage;
  transport: ReviewTransport;
  labels: ReviewWalkLabels;
  onModelContext?: (text: string) => void;
  /** Why the result that opened the card failed, shown until Försök igen reads the queue. */
  cause?: unknown;
}) {
  const walk = useReviewWalk({
    initial,
    failure: cause,
    transport,
    labels,
    onModelContext,
  });
  const eyebrow = `${labels.appName} · ${labels.kind}`;
  const frame = (body: ReactNode, busy = false) => (
    <Card
      className="work-compact-card review-walk"
      aria-label={labels.kind}
      aria-busy={busy || undefined}
      eyebrow={eyebrow}
    >
      {body}
      <ReceiptBar receipt={walk.receipt} />
    </Card>
  );

  if (walk.start.phase === "failed")
    return frame(
      <ErrorNotice
        locale={labels.dateLocale}
        subject="work:review"
        cause={walk.start.cause}
        onRetry={walk.retryStart}
      />,
    );
  if (walk.start.phase === "reading") return frame(<WalkSkeleton />, true);
  if (walk.empty)
    return frame(<EmptyState title={labels.empty} hint={labels.emptyHint} />);
  if (walk.finished)
    return frame(
      <div className="review-walk__end">
        <p className="review-walk__end-title">{labels.finished}</p>
        <p className="work-compact-status">
          {labels.finishedSummary(walk.counts.decided, walk.counts.skipped)}
        </p>
      </div>,
    );
  if (walk.waiting || !walk.current)
    return frame(
      walk.more === "failed" ? (
        <ErrorNotice
          locale={labels.dateLocale}
          subject="work:review"
          onRetry={walk.retryMore}
        />
      ) : (
        <WalkSkeleton label={labels.loadingMore} />
      ),
      walk.more !== "failed",
    );
  return frame(
    <WalkTask
      walk={walk}
      task={walk.current}
      labels={labels}
      transport={transport}
    />,
  );
}

/** The Task shown, its reason and the decisions. */
function WalkTask({
  walk,
  task,
  labels,
  transport,
}: {
  walk: ReviewWalk;
  task: ReviewQueueTask;
  labels: ReviewWalkLabels;
  transport: ReviewTransport;
}) {
  const { busy, moving, setMoving, position, total } = walk;
  const reason = reviewReason(task, labels, new Date());
  const overdue = task.bucket === "overdue" || task.bucket === "long_overdue";
  const place = task.project_title ?? task.domain_name;
  const moveRef = useRef<HTMLButtonElement>(null);
  const tomorrowRef = useRef<HTMLButtonElement>(null);
  // Where the focus goes when the row turns: onto the first day after Flytta, back onto Flytta after Avbryt or a move.
  const turned = useRef(false);
  useEffect(() => {
    if (!turned.current) return;
    (moving ? tomorrowRef : moveRef).current?.focus();
  }, [moving]);
  const turn = (next: boolean) => {
    turned.current = true;
    setMoving(next);
  };
  // Busy keeps every button in place and focusable (aria-disabled), so the focus never falls to the page mid-write.
  const choice = (
    key: string,
    label: string,
    pick: ReviewChoice,
    ref?: Ref<HTMLButtonElement>,
  ) => (
    <button
      key={key}
      ref={ref}
      type="button"
      className={buttonClass("secondary", "review-walk__choice")}
      aria-disabled={busy !== undefined || undefined}
      aria-busy={busy === key || undefined}
      onClick={() => {
        if (busy === undefined) walk.choose(pick);
      }}
    >
      {busy === key ? labels.saving : label}
    </button>
  );
  return (
    <>
      <div className="review-walk__head">
        <Progress
          done={position - 1}
          total={total}
          label={labels.position(position, total)}
          layout="bar"
        />
        <button
          type="button"
          className={buttonClass("quiet", "sk-btn--compact review-walk__skip")}
          aria-disabled={busy !== undefined || undefined}
          onClick={() => {
            if (busy === undefined) walk.skip();
          }}
        >
          {labels.skip}
        </button>
      </div>
      <h2 className="sk-card__title review-walk__title">{task.title}</h2>
      <p className="work-compact-status review-walk__meta">
        <span data-tone={overdue ? "overdue" : undefined}>{reason}</span>
        {place ? ` · ${place}` : null}
      </p>
      {moving ? (
        <div
          role="group"
          aria-label={labels.moveChoices}
          className="review-walk__choices"
          data-count={3}
        >
          {choice(
            "tomorrow",
            labels.tomorrow,
            { decision: "move", when: "tomorrow" },
            tomorrowRef,
          )}
          {choice("next_week", labels.nextWeek, {
            decision: "move",
            when: "next_week",
          })}
          <button
            type="button"
            className={buttonClass("quiet", "review-walk__choice")}
            aria-disabled={busy !== undefined || undefined}
            onClick={() => {
              if (busy === undefined) turn(false);
            }}
          >
            {labels.cancel}
          </button>
        </div>
      ) : (
        <div
          role="group"
          aria-label={labels.decisions}
          className="review-walk__choices"
          data-count={transport.trash ? 4 : 3}
        >
          {choice("done", labels.done, { decision: "done" })}
          {choice("keep", labels.keep, { decision: "keep" })}
          <button
            ref={moveRef}
            type="button"
            className={buttonClass("secondary", "review-walk__choice")}
            aria-disabled={busy !== undefined || undefined}
            onClick={() => {
              if (busy === undefined) turn(true);
            }}
          >
            {labels.move}
          </button>
          {transport.trash
            ? choice("trash", labels.trash, { decision: "trash" })
            : null}
        </div>
      )}
      {walk.notice ? (
        <NoticeRow notice={walk.notice} locale={labels.dateLocale} />
      ) : null}
      <p className="review-walk__sr" aria-live="polite">
        {position > 1 ? labels.announce(position, total, task.title) : ""}
      </p>
    </>
  );
}

/** The card while the queue is read: the head and title as bars, the decisions' row held. */
function WalkSkeleton({ label }: { label?: string }) {
  return (
    <div
      className="review-walk__skeleton"
      aria-hidden={label ? undefined : true}
    >
      <span className="sidekick-wait-block review-walk__bar" />
      <span className="sidekick-wait-block review-walk__bar review-walk__bar--title" />
      {label ? <p className="work-compact-status">{label}</p> : null}
    </div>
  );
}
