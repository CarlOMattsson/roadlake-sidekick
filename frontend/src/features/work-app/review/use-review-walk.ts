import { useCallback, useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { useReceipt, type ReceiptState } from "../../mcp-apps/ui/receipt";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import { writeFailure } from "../transport/transport";
import { useSingleFlight } from "../shared/use-single-flight";
import { rowReceipt } from "../shared/use-undo-receipts";
import {
  reviewQueuePage,
  undoOfReview,
  type ReviewChoice,
  type ReviewQueuePage,
  type ReviewQueueTask,
  type ReviewScope,
  type ReviewUndo,
} from "./review-walk-data";
import type { ReviewCounts, ReviewWalkLabels } from "./review-walk-labels";
import type { ReviewTransport } from "./review-walk-transport";

/** A failed write as the card's notice row: what went wrong and, when it can help, one action. */
export type ReviewNotice = {
  message: string;
  actionLabel?: string;
  action?: () => void;
};

/** The walk: the Tasks read so far in queue order, the one shown, and where the next page starts. */
type Walk = {
  queue: ReviewQueueTask[];
  index: number;
  scope: ReviewScope;
  cursor: string | null;
  /** The queue's size when the walk began; grows only if more Tasks turn up than it said. */
  total: number;
  counts: ReviewCounts;
};

/** One saved decision, kept while its Ångra is offered. */
type Decided = {
  index: number;
  task: ReviewQueueTask;
  choice: ReviewChoice;
  undo: ReviewUndo;
  /** The Task's version after the decision: what the card holds when Ångra writes nothing. */
  version: number;
};

type Start =
  | { phase: "reading" }
  | { phase: "failed"; cause: unknown }
  | { phase: "ready" };

const NO_COUNTS: ReviewCounts = {
  decided: 0,
  done: 0,
  kept: 0,
  moved: 0,
  trashed: 0,
  skipped: 0,
};

const COUNT_OF: Record<ReviewChoice["decision"], keyof ReviewCounts> = {
  done: "done",
  keep: "kept",
  move: "moved",
  trash: "trashed",
};

/** Read the next page when this few Tasks are left of the ones read, so the next one is there when it is due. */
const READ_AHEAD = 3;

function walkFrom(page: ReviewQueuePage): Walk {
  return {
    queue: page.tasks,
    index: 0,
    scope: page.scope,
    cursor: page.nextCursor,
    total: page.remainingTotal,
    counts: NO_COUNTS,
  };
}

function counted(
  counts: ReviewCounts,
  choice: ReviewChoice,
  step: 1 | -1,
): ReviewCounts {
  const key = COUNT_OF[choice.decision];
  return {
    ...counts,
    decided: counts.decided + step,
    [key]: counts[key] + step,
  };
}

/** The receipt's words for a decision: "Klar: Ring Lena", "Flyttad till imorgon: Ring Lena". */
function receiptWord(choice: ReviewChoice, labels: ReviewWalkLabels): string {
  return choice.decision === "move"
    ? labels.receipt[choice.when]
    : labels.receipt[choice.decision];
}

/**
 * The walk through the review queue, one Task at a time, in the card itself: every tap is saved at once through the
 * host (one Task per call, so a change never covers more Tasks than the owner just saw), the receipt bar offers Ångra
 * for the last decision, and the next page is read before it is needed. Without a page (an error result, a room mounted
 * without one) the first page is read here, with Försök igen when that fails.
 */
export function useReviewWalk({
  initial,
  failure,
  transport,
  labels,
  onModelContext,
}: {
  initial?: ReviewQueuePage;
  /** The cause of an error result that opened the card without a page: shown first, Försök igen reads the queue. */
  failure?: unknown;
  transport: ReviewTransport;
  labels: ReviewWalkLabels;
  /** Told after each decision and Ångra, so the conversation knows what the card did. */
  onModelContext?: (text: string) => void;
}) {
  const [walk, setWalk] = useState<Walk | undefined>(() =>
    initial ? walkFrom(initial) : undefined,
  );
  const [start, setStart] = useState<Start>(
    initial
      ? { phase: "ready" }
      : failure !== undefined
        ? { phase: "failed", cause: failure }
        : { phase: "reading" },
  );
  const [startAttempt, setStartAttempt] = useState(0);
  const [more, setMore] = useState<"idle" | "loading" | "failed">("idle");
  const [busy, setBusy] = useState<string>();
  const [moving, setMoving] = useState(false);
  const [notice, setNotice] = useState<ReviewNotice>();
  const flight = useSingleFlight();
  const alive = useMounted();
  const receipt: ReceiptState = useReceipt();
  const pending = useRef<PendingKey | undefined>(undefined);
  const pendingUndo = useRef<PendingKey | undefined>(undefined);
  // The latest walk, for the handlers that run after an await.
  const walkRef = useRef(walk);
  walkRef.current = walk;

  // The first page, when the result carried none.
  useEffect(() => {
    if (start.phase !== "reading") return undefined;
    let live = true;
    transport
      .readQueue("suggested", null)
      .then((value) => {
        if (!live) return;
        const page = reviewQueuePage(value);
        if (!page) throw new Error("not a review queue");
        setWalk(walkFrom(page));
        setStart({ phase: "ready" });
      })
      .catch((cause: unknown) => {
        if (live) setStart({ phase: "failed", cause });
      });
    return () => {
      live = false;
    };
  }, [start.phase, startAttempt, transport]);

  const retryStart = useCallback(() => {
    setStart({ phase: "reading" });
    setStartAttempt((value) => value + 1);
  }, []);

  const readMore = useCallback(() => {
    const now = walkRef.current;
    if (!now?.cursor) return;
    const { scope, cursor } = now;
    setMore("loading");
    transport
      .readQueue(scope, cursor)
      .then((value) => {
        if (!alive.current) return;
        const page = reviewQueuePage(value);
        if (!page) throw new Error("not a review queue");
        setWalk((prev) => {
          if (!prev || prev.cursor !== cursor) return prev;
          const known = new Set(prev.queue.map((task) => task.id));
          const queue = [
            ...prev.queue,
            ...page.tasks.filter((task) => !known.has(task.id)),
          ];
          return { ...prev, queue, cursor: page.nextCursor };
        });
        setMore("idle");
      })
      .catch(() => {
        if (alive.current) setMore("failed");
      });
  }, [transport, alive]);

  // Reads ahead while the owner is still on the Tasks already read.
  const left = walk ? walk.queue.length - walk.index : 0;
  const hasCursor = Boolean(walk?.cursor);
  useEffect(() => {
    if (hasCursor && more === "idle" && left <= READ_AHEAD) readMore();
  }, [hasCursor, more, left, readMore]);

  const current = walk ? walk.queue[walk.index] : undefined;

  function tell(counts: ReviewCounts, total: number) {
    onModelContext?.(
      labels.modelNote(counts, Math.max(0, total - counts.decided)),
    );
  }

  function patchCurrent(task: ReviewQueueTask) {
    setWalk((prev) =>
      prev
        ? {
            ...prev,
            queue: prev.queue.map((item) =>
              item.id === task.id ? task : item,
            ),
          }
        : prev,
    );
  }

  /** Reads the Task again after a conflict: its new version, title and due date, so the owner can choose again. */
  async function reread(task: ReviewQueueTask) {
    setNotice(undefined);
    pending.current = undefined;
    try {
      const { task: fresh } = await transport.getTask(task.id);
      if (!alive.current) return;
      patchCurrent({
        ...task,
        version: fresh.version,
        title: fresh.title,
        status: fresh.status,
        due_at: fresh.due_at ?? null,
      });
    } catch {
      if (alive.current)
        setNotice({
          message: labels.conflict,
          actionLabel: labels.reread,
          action: () => void reread(task),
        });
    }
  }

  function failed(error: unknown, task: ReviewQueueTask, retry: () => void) {
    switch (writeFailure(error)) {
      case "conflict":
        pending.current = undefined;
        setNotice({
          message: labels.conflict,
          actionLabel: labels.reread,
          action: () => void reread(task),
        });
        return;
      case "not_found":
        pending.current = undefined;
        setNotice({
          message: labels.gone,
          actionLabel: labels.skip,
          action: skip,
        });
        return;
      case "forbidden":
        pending.current = undefined;
        setNotice({ message: labels.forbidden });
        return;
      case "invalid":
        pending.current = undefined;
        setNotice({ message: labels.failed });
        return;
      default:
        setNotice({
          message: labels.failed,
          actionLabel: labels.retry,
          action: retry,
        });
    }
  }

  /** Saves one decision on the Task shown, then shows the next one with the receipt and its Ångra. */
  async function choose(choice: ReviewChoice) {
    const now = walkRef.current;
    const task = now ? now.queue[now.index] : undefined;
    if (!now || !task || !flight.enter()) return;
    const index = now.index;
    const busyKey = choice.decision === "move" ? choice.when : choice.decision;
    setBusy(busyKey);
    setNotice(undefined);
    try {
      const signature = JSON.stringify([task.id, task.version, choice]);
      const key = keyFor(pending.current, signature);
      pending.current = key;
      let undo: ReviewUndo;
      let version = task.version;
      if (choice.decision === "trash") {
        const trashed = await transport.trashTask(
          task.id,
          task.version,
          key.key,
        );
        undo = { kind: "restore", trashVersion: trashed.version };
      } else {
        const answer = await transport.review(
          [
            {
              task_id: task.id,
              expected_version: task.version,
              decision: choice.decision,
              ...(choice.decision === "move" ? { when: choice.when } : {}),
            },
          ],
          key.key,
        );
        const reviewed = answer.tasks.find((item) => item.id === task.id);
        if (!reviewed) throw new Error("decision not in the answer");
        undo = undoOfReview(reviewed);
        version = reviewed.version;
      }
      pending.current = undefined;
      if (!alive.current) return;
      const decided: Decided = { index, task, choice, undo, version };
      const counts = counted(now.counts, choice, 1);
      setWalk((prev) => (prev ? { ...prev, index: index + 1, counts } : prev));
      setMoving(false);
      receipt.show({
        message: rowReceipt(receiptWord(choice, labels), task.title),
        undo: { label: labels.undo, onUndo: () => undoDecision(decided) },
      });
      tell(counts, now.total);
    } catch (error) {
      if (alive.current) failed(error, task, () => void choose(choice));
    } finally {
      flight.leave();
      if (alive.current) setBusy(undefined);
    }
  }

  /** Ångra: the opposite write of the last decision, then that Task is shown again with its new version. */
  async function undoDecision(decided: Decided) {
    if (!flight.enter()) return;
    const { task, undo } = decided;
    setBusy("undo");
    setNotice(undefined);
    try {
      let version = decided.version;
      const signature = JSON.stringify([task.id, undo]);
      const key = keyFor(pendingUndo.current, signature);
      pendingUndo.current = key;
      if (undo.kind === "update") {
        const answer = await transport.updateTask(
          task.id,
          undo.version,
          undo.changes,
          key.key,
        );
        version = answer.task.version;
      } else if (undo.kind === "restore") {
        await transport.restoreTask(task.id, undo.trashVersion, key.key);
        version = (await transport.getTask(task.id)).task.version;
      }
      pendingUndo.current = undefined;
      if (!alive.current) return;
      const now = walkRef.current;
      if (!now) return;
      const counts = counted(now.counts, decided.choice, -1);
      setWalk({
        ...now,
        index: decided.index,
        counts,
        queue: now.queue.map((item) =>
          item.id === task.id ? { ...task, version } : item,
        ),
      });
      setMoving(false);
      tell(counts, now.total);
    } catch {
      if (alive.current)
        setNotice({
          message: labels.undoFailed,
          actionLabel: labels.retry,
          action: () => void undoDecision(decided),
        });
    } finally {
      flight.leave();
      if (alive.current) setBusy(undefined);
    }
  }

  /** Passes the Task by: nothing is written, and it stays in the queue for another time. */
  function skip() {
    if (flight.isRunning()) return;
    pending.current = undefined;
    setNotice(undefined);
    setMoving(false);
    setWalk((prev) =>
      prev && prev.index < prev.queue.length
        ? {
            ...prev,
            index: prev.index + 1,
            counts: { ...prev.counts, skipped: prev.counts.skipped + 1 },
          }
        : prev,
    );
  }

  const total = walk ? Math.max(walk.total, walk.queue.length) : 0;
  return {
    start,
    retryStart,
    current,
    position: walk ? walk.index + 1 : 0,
    total,
    /** The queue was empty when the walk began. */
    empty:
      start.phase === "ready" && walk !== undefined && walk.queue.length === 0,
    /** Every Task of the queue has been shown. */
    finished:
      walk !== undefined && walk.queue.length > 0 && !current && !walk.cursor,
    /** The shown Tasks are through and the next page is on its way, or failed. */
    waiting: walk !== undefined && !current && Boolean(walk.cursor),
    more,
    retryMore: readMore,
    counts: walk?.counts ?? NO_COUNTS,
    busy,
    moving,
    setMoving,
    notice,
    choose: (choice: ReviewChoice) => void choose(choice),
    skip,
    receipt,
  };
}

export type ReviewWalk = ReturnType<typeof useReviewWalk>;
