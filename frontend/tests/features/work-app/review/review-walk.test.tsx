import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReviewWalkCard } from "@/features/work-app/review/review-walk-card";
import {
  reviewQueuePage,
  reviewReason,
  undoOfReview,
  type ReviewedTask,
  type ReviewQueuePage,
} from "@/features/work-app/review/review-walk-data";
import {
  reviewWalkEn,
  reviewWalkLabelsFor,
  reviewWalkSv,
} from "@/features/work-app/review/review-walk-labels";
import type { ReviewTransport } from "@/features/work-app/review/review-walk-transport";
import { rootFromToolResult } from "@/features/work-app/transport/transport";

/*
 * The review card walks get_review_queue's page one Task at a time: one decision per call, the receipt's Ångra writes
 * the opposite, and the next page is read ahead. Simulated transport: this proves the card's wiring, not a real Claude
 * or Android host.
 */

const NOW = new Date("2026-11-20T09:00:00+01:00");

function task(n: number, bucket = "overdue", extra: object = {}) {
  return {
    id: `t${n}`,
    version: 3,
    title: `Uppgift ${n}`,
    status: "todo",
    bucket: bucket as "overdue",
    reason: "overdue 3 weeks",
    due_at: "2026-10-28T22:59:00Z",
    follow_up_at: null,
    project_id: null,
    project_title: null,
    domain_id: null,
    domain_name: null,
    ...extra,
  };
}

const page: ReviewQueuePage = {
  tasks: [task(1, "likely_done"), task(2), task(3), task(4), task(5)],
  scope: "all",
  remainingTotal: 40,
  nextCursor: "c2",
};

function reviewedOf(
  id: string,
  decision: string,
  status: string,
  previous = "todo",
): ReviewedTask {
  return {
    id,
    version: 4,
    decision: decision as "done",
    status,
    due_at: "2026-10-28T22:59:00Z",
    archived: false,
    previous: {
      status: previous,
      due_at: "2026-10-28T22:59:00Z",
      waiting_since: null,
      follow_up_at: null,
      attention_requested: false,
      last_completed_at: null,
      archived_at: null,
    },
  };
}

function transport(overrides: Partial<ReviewTransport> = {}): ReviewTransport {
  return {
    getTask: vi.fn().mockResolvedValue({
      task: {
        id: "t1",
        version: 9,
        title: "Uppgift 1 (ny)",
        status: "todo",
        due_at: null,
      },
    }),
    updateTask: vi.fn().mockResolvedValue({ task: { id: "t1", version: 5 } }),
    trashTask: vi.fn().mockResolvedValue({ version: 1 }),
    restoreTask: vi.fn().mockResolvedValue({}),
    readQueue: vi.fn().mockResolvedValue({
      tasks: [task(6)],
      scope: "all",
      remaining_total: 35,
      bucket_counts: {},
      next_cursor: null,
    }),
    review: vi.fn((items: { task_id: string; decision: string }[]) =>
      Promise.resolve({
        count: 1,
        tasks: [
          reviewedOf(
            items[0]!.task_id,
            items[0]!.decision,
            items[0]!.decision === "done" ? "completed" : "todo",
          ),
        ],
      }),
    ),
    trash: true,
    ...overrides,
  };
}

function keysOf(value: unknown): string[] {
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, inner]) => [
    key,
    ...keysOf(inner).map((k) => `${key}.${k}`),
  ]);
}

describe("review card words", () => {
  it("have the same keys in sv and en, and Swedish is the default", () => {
    expect(keysOf(reviewWalkEn)).toEqual(keysOf(reviewWalkSv));
    expect(reviewWalkLabelsFor("sv-SE")).toBe(reviewWalkSv);
    expect(reviewWalkLabelsFor("en")).toBe(reviewWalkEn);
  });

  it("say why a Task is in the queue in the app's language, never the server's English", () => {
    vi.useFakeTimers({ now: NOW });
    expect(reviewReason(task(1, "likely_done"), reviewWalkSv, NOW)).toBe(
      "Alla steg klara",
    );
    expect(reviewReason(task(2, "long_overdue"), reviewWalkSv, NOW)).toBe(
      "Försenad sedan 28 okt",
    );
    expect(
      reviewReason(
        task(3, "follow_up_due", { follow_up_at: "2026-11-17T22:59:00Z" }),
        reviewWalkEn,
        NOW,
      ),
    ).toMatch(/^Follow up, since /);
    expect(
      reviewReason(task(4, "other", { due_at: null }), reviewWalkSv, NOW),
    ).toBe("Inget datum");
    vi.useRealTimers();
  });
});

describe("the queue page", () => {
  it("is read from a get_review_queue result, with suggested when the result names no scope", () => {
    const result = {
      tasks: [task(1)],
      remaining_total: 1,
      bucket_counts: { overdue: 1 },
      next_cursor: null,
    };
    expect(reviewQueuePage(result)?.scope).toBe("suggested");
    expect(reviewQueuePage({ ...result, scope: "all" })?.scope).toBe("all");
    expect(reviewQueuePage({ tasks: [] })).toBeUndefined();
    expect(rootFromToolResult({ ...result, scope: "all" })).toMatchObject({
      kind: "review",
      page: { remainingTotal: 1, nextCursor: null },
    });
  });

  it("undoes Done by the earlier status, a recurring Done by its date, a move by its date, and Keep by nothing", () => {
    expect(undoOfReview(reviewedOf("t1", "done", "completed"))).toEqual({
      kind: "update",
      version: 4,
      changes: { status: "todo" },
    });
    expect(undoOfReview(reviewedOf("t1", "done", "todo"))).toMatchObject({
      kind: "update",
      changes: { due_at: "2026-10-28T22:59:00Z", last_completed_at: null },
    });
    expect(undoOfReview(reviewedOf("t1", "move", "todo"))).toMatchObject({
      changes: { due_at: "2026-10-28T22:59:00Z" },
    });
    expect(undoOfReview(reviewedOf("t1", "keep", "todo"))).toEqual({
      kind: "none",
    });
  });
});

function renderCard(
  t: ReviewTransport,
  initial: ReviewQueuePage | null = page,
  cause?: unknown,
) {
  const onModelContext = vi.fn();
  render(
    <div className="sidekick-work">
      <ReviewWalkCard
        initial={initial ?? undefined}
        cause={cause}
        transport={t}
        labels={reviewWalkSv}
        onModelContext={onModelContext}
      />
    </div>,
  );
  return { onModelContext };
}

/** Clicks a button and lets the write it starts settle. */
async function click(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const decisions = () =>
  screen.getByRole("group", { name: "Vad ska hända med uppgiften?" });

describe("the review card", () => {
  it("saves one Task per tap, then shows the next one with the receipt", async () => {
    const t = transport();
    const { onModelContext } = renderCard(t);
    expect(screen.getByText("1 av 40")).toBeTruthy();
    await click("Klar");
    expect(t.review).toHaveBeenCalledTimes(1);
    expect(vi.mocked(t.review).mock.calls[0]![0]).toEqual([
      { task_id: "t1", expected_version: 3, decision: "done" },
    ]);
    expect(screen.getByText("2 av 40")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Uppgift 2" })).toBeTruthy();
    expect(screen.getByText("Klar: Uppgift 1")).toBeTruthy();
    expect(onModelContext).toHaveBeenLastCalledWith(
      expect.stringContaining("1 beslut sparade (1 klara"),
    );
  });

  it("Ångra writes the earlier status against the version the decision left and shows that Task again", async () => {
    const t = transport();
    renderCard(t);
    await click("Klar");
    await click("Ångra");
    expect(t.updateTask).toHaveBeenCalledWith(
      "t1",
      4,
      { status: "todo" },
      expect.any(String),
    );
    expect(screen.getByText("1 av 40")).toBeTruthy();
    // The Task now holds the version the undo left, so the next decision is written against it.
    await click("Behåll");
    expect(vi.mocked(t.review).mock.calls[1]![0]).toEqual([
      { task_id: "t1", expected_version: 5, decision: "keep" },
    ]);
  });

  it("Flytta turns the row into its days and Avbryt turns it back", async () => {
    const t = transport();
    renderCard(t);
    fireEvent.click(screen.getByRole("button", { name: "Flytta" }));
    expect(screen.getByRole("group", { name: "Flytta till" })).toBeTruthy();
    expect(document.activeElement?.textContent).toBe("Imorgon");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(document.activeElement?.textContent).toBe("Flytta");
    fireEvent.click(screen.getByRole("button", { name: "Flytta" }));
    await click("Nästa vecka");
    expect(screen.queryByRole("group", { name: "Flytta till" })).toBeNull();
    expect(vi.mocked(t.review).mock.calls[0]![0]).toEqual([
      {
        task_id: "t1",
        expected_version: 3,
        decision: "move",
        when: "next_week",
      },
    ]);
    expect(
      screen.getByText("Flyttad till nästa vecka: Uppgift 1"),
    ).toBeTruthy();
  });

  it("leaves Ta bort out where the host has no trash", () => {
    renderCard(transport({ trash: false }));
    expect(
      Array.from(decisions().querySelectorAll("button")).map(
        (b) => b.textContent,
      ),
    ).toEqual(["Klar", "Behåll", "Flytta"]);
  });

  it("a conflict offers to read the Task again; a failed write retries with the same key", async () => {
    const conflict = Object.assign(new Error("conflict"), { code: "conflict" });
    const down = Object.assign(new Error("down"), { code: "unavailable" });
    const review = vi
      .fn()
      .mockRejectedValueOnce(conflict)
      .mockRejectedValueOnce(down)
      .mockRejectedValueOnce(down)
      .mockResolvedValue({
        count: 1,
        tasks: [reviewedOf("t1", "keep", "todo")],
      });
    const t = transport({ review });
    renderCard(t);
    await click("Behåll");
    expect(
      screen.getByText("Uppgiften ändrades nyss någon annanstans."),
    ).toBeTruthy();
    await click("Läs in den igen");
    expect(t.getTask).toHaveBeenCalledWith("t1");
    expect(
      screen.getByRole("heading", { name: "Uppgift 1 (ny)" }),
    ).toBeTruthy();
    await click("Behåll");
    expect(review.mock.calls[1]![0]).toEqual([
      { task_id: "t1", expected_version: 9, decision: "keep" },
    ]);
    expect(screen.getByText("Beslutet kunde inte sparas.")).toBeTruthy();
    await click("Försök igen");
    await click("Försök igen");
    // The same decision on the same version keeps its key, so the server replays it rather than writing twice.
    expect(review.mock.calls[2]![1]).toBe(review.mock.calls[1]![1]);
    expect(review.mock.calls[3]![1]).toBe(review.mock.calls[1]![1]);
    expect(screen.getByText("2 av 40")).toBeTruthy();
  });

  it("reads the next page ahead with the page's scope and cursor", async () => {
    const t = transport();
    renderCard(t);
    expect(t.readQueue).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Hoppa över" }));
    await click("Hoppa över");
    expect(t.readQueue).toHaveBeenCalledWith("all", "c2");
    for (let n = 0; n < 4; n++) await click("Hoppa över");
    expect(screen.getByText("Genomgången är klar")).toBeTruthy();
    expect(screen.getByText("0 beslut · 6 hoppade över")).toBeTruthy();
  });

  it("an empty queue says so", () => {
    renderCard(transport(), {
      ...page,
      tasks: [],
      remainingTotal: 0,
      nextCursor: null,
    });
    expect(screen.getByText("Inget att gå igenom")).toBeTruthy();
  });

  it("an error result shows the read error, and Försök igen reads the queue", async () => {
    const t = transport();
    renderCard(t, null, new Error("failed"));
    expect(screen.getByText("Genomgången kunde inte hämtas")).toBeTruthy();
    await click("Försök igen");
    expect(t.readQueue).toHaveBeenCalledWith("suggested", null);
    expect(screen.getByRole("heading", { name: "Uppgift 6" })).toBeTruthy();
  });
});
