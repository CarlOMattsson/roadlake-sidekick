/**
 * The review queue as the card reads it, and the pure parts of a walk through it: which result is a queue page, why a
 * Task is in the queue in the owner's words, and what Ångra writes back after a decision. No React and no clock reads:
 * the caller passes `now`.
 */
import { isPlainObject, recordGuard, shapeAt } from "../../../lib/mcp/shape";
import type { ToolResults } from "../../../lib/mcp/tool-results.generated";
import { getReviewQueueResultShape } from "../../../lib/mcp/tool-shapes.generated";
import { workDate } from "../../mcp-apps/ui/due";
import {
  isTaskStatus,
  type WorkTaskChanges,
} from "../transport/transport-records";
import type { ReviewWalkLabels } from "./review-walk-labels";

type QueueResult = ToolResults["get_review_queue"];
export type ReviewScope = QueueResult["scope"];
export type ReviewQueueTask = QueueResult["tasks"][number];
export type ReviewedTask = ToolResults["review_tasks"]["tasks"][number];

/** One page of the queue: its Tasks, the queue's size when it was read, and where the next page starts. */
export type ReviewQueuePage = {
  tasks: ReviewQueueTask[];
  scope: ReviewScope;
  remainingTotal: number;
  nextCursor: string | null;
};

const isQueueTask = recordGuard<ReviewQueueTask>(
  shapeAt(getReviewQueueResultShape, "tasks", "[]"),
  ["id", "version", "title", "status", "bucket"],
);

/**
 * The page a get_review_queue result carries, or undefined when the value is not one. `scope` is read when present;
 * a result without it was read with the server's default, "suggested".
 */
export function reviewQueuePage(value: unknown): ReviewQueuePage | undefined {
  if (!isPlainObject(value)) return undefined;
  const { tasks, remaining_total: total, bucket_counts: counts } = value;
  if (
    !Array.isArray(tasks) ||
    !tasks.every(isQueueTask) ||
    typeof total !== "number" ||
    !isPlainObject(counts)
  )
    return undefined;
  return {
    tasks,
    scope: value.scope === "all" ? "all" : "suggested",
    remainingTotal: total,
    nextCursor:
      typeof value.next_cursor === "string" ? value.next_cursor : null,
  };
}

/**
 * Why the Task is in the queue, in the owner's words, from its bucket and dates: the server's `reason` is English and
 * written to be read aloud, so the card says it again in the app's language.
 */
export function reviewReason(
  task: Pick<ReviewQueueTask, "bucket" | "due_at" | "follow_up_at">,
  labels: ReviewWalkLabels,
  now: Date,
): string {
  const day = (value: string | null | undefined) =>
    workDate(value, now, labels.dateLocale, { inline: true });
  switch (task.bucket) {
    case "likely_done":
      return labels.reason.likelyDone;
    case "long_overdue":
    case "overdue": {
      const date = day(task.due_at);
      return date ? labels.reason.overdue(date) : labels.reason.noDue;
    }
    case "follow_up_due": {
      const date = day(task.follow_up_at);
      return date ? labels.reason.followUp(date) : labels.reason.noDue;
    }
    default: {
      const date = day(task.due_at);
      return date ? labels.reason.due(date) : labels.reason.noDue;
    }
  }
}

/** The decisions the card offers. `move` carries its day; `trash` goes through the trash, not review_tasks. */
export type ReviewChoice =
  | { decision: "done" }
  | { decision: "keep" }
  | { decision: "move"; when: "tomorrow" | "next_week" }
  | { decision: "trash" };

/** What Ångra writes after a decision: an update of the Task, the trash's restore, or nothing (Behåll). */
export type ReviewUndo =
  | { kind: "update"; version: number; changes: WorkTaskChanges }
  | { kind: "restore"; trashVersion: number }
  | { kind: "none" };

/**
 * Ångra after a saved review decision: the opposite ordinary write from `previous`. Done writes the earlier status
 * back; a recurring Task stays open after Done with its next due date, so its due date and last completion go back
 * instead. Move writes the earlier due date. Keep changed nothing but the review mark, so it has nothing to write.
 */
export function undoOfReview(reviewed: ReviewedTask): ReviewUndo {
  const { previous } = reviewed;
  switch (reviewed.decision) {
    case "done":
      if (reviewed.status !== previous.status)
        return isTaskStatus(previous.status)
          ? {
              kind: "update",
              version: reviewed.version,
              changes: { status: previous.status },
            }
          : { kind: "none" };
      return {
        kind: "update",
        version: reviewed.version,
        changes: {
          due_at: previous.due_at,
          last_completed_at: previous.last_completed_at,
        },
      };
    case "move":
      return {
        kind: "update",
        version: reviewed.version,
        changes: { due_at: previous.due_at },
      };
    default:
      return { kind: "none" };
  }
}
