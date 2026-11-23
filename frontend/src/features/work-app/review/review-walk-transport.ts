import type { ToolResults } from "../../../lib/mcp/tool-results.generated";
import type { RoomTransport } from "../../mcp-apps/room-types";
import { toolOffered } from "../../mcp-apps/tool-support";
import type { WorkTransport } from "../transport/transport";
import type { ReviewScope } from "./review-walk-data";

/** One decision as review_tasks takes it: the card sends one per tap. */
export type ReviewItem = {
  task_id: string;
  expected_version: number;
  decision: "done" | "keep" | "move";
  when?: "tomorrow" | "next_week";
};

/**
 * What the review card reads and writes, all through the host's tools/call: the queue's next page, the decisions
 * (review_tasks), and the Work room's own Task writes for the trash and for Ångra. `trash` is false where the host does
 * not offer both trash tools, so the card leaves Ta bort out.
 */
export type ReviewTransport = Pick<
  WorkTransport,
  "getTask" | "updateTask" | "trashTask" | "restoreTask"
> & {
  readQueue: (scope: ReviewScope, cursor: string | null) => Promise<unknown>;
  review: (
    items: ReviewItem[],
    idempotencyKey: string,
  ) => Promise<ToolResults["review_tasks"]>;
  trash: boolean;
};

export function createReviewTransport(
  work: WorkTransport,
  call: RoomTransport["call"],
): ReviewTransport {
  return {
    getTask: work.getTask,
    updateTask: work.updateTask,
    trashTask: work.trashTask,
    restoreTask: work.restoreTask,
    readQueue: (scope, cursor) =>
      call("get_review_queue", {
        scope,
        ...(cursor ? { cursor } : {}),
      }),
    review: (items, idempotencyKey) =>
      call("review_tasks", { items, idempotency_key: idempotencyKey }),
    trash:
      toolOffered(work, "move_to_trash") &&
      toolOffered(work, "restore_from_trash"),
  };
}
