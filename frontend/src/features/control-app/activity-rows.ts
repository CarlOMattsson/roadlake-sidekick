import type { ControlLabels } from "./labels";
import type { ActivityRecord, ChangeRecord } from "./transport";

/** A change and the activity entry it caused are written within the same request, so they are seconds apart at most. */
const SAME_ACTION_MS = 5000;

/** Activity of this category exists only in the activity feed, so no change row stands for it. */
const AI_CATEGORY = "ai_steps";

/**
 * The activity entries worth a row of their own. An entry that records the same action as a change row (the same
 * record, close in time) is dropped, since the change row already says it and has the Undo or Restore button.
 * AI rows are never dropped.
 */
export function withoutRepeatedActivity<T extends ActivityRecord>(
  changes: readonly Pick<ChangeRecord, "id" | "occurred_at">[],
  entries: readonly T[],
): T[] {
  const times = new Map<string, number[]>();
  for (const change of changes) {
    const at = Date.parse(change.occurred_at);
    if (Number.isNaN(at)) continue;
    times.set(change.id, [...(times.get(change.id) ?? []), at]);
  }
  return entries.filter((entry) => {
    if (entry.category === AI_CATEGORY || !entry.aggregate_id) return true;
    const at = Date.parse(entry.occurred_at);
    if (Number.isNaN(at)) return true;
    return !times
      .get(entry.aggregate_id)
      ?.some((changeAt) => Math.abs(changeAt - at) <= SAME_ACTION_MS);
  });
}

/**
 * The text of an activity row in the app's language: the operation's sentence, with the task's name after it when the
 * entry carries one. An operation the app has no sentence for shows the stored summary.
 */
export function activityText(
  labels: ControlLabels,
  entry: ActivityRecord,
): string {
  const values = entry.after_values ?? {};
  const state = typeof values.state === "string" ? values.state : "";
  const sentence =
    (entry.operation.startsWith("run_")
      ? labels.activityRunStates[state]
      : undefined) ?? labels.activityOperations[entry.operation];
  if (!sentence) return entry.summary.trim();
  const title = typeof values.title === "string" ? values.title.trim() : "";
  return title ? `${sentence}: ${title}` : sentence;
}
